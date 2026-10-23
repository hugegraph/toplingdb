#!/usr/bin/env bash
# Verify the native configuration entry point used by HugeGraph container builds.
set -euo pipefail
jar="$(realpath "${1:?usage: test_topling_jni.sh path/to/rocksdbjni.jar}")"
probe="$(mktemp -d)"
trap 'rm -rf "$probe"' EXIT
unzip -p "$jar" librocksdbjni-linux64.so > "$probe/librocksdbjni-linux64.so"
if [ ! -e /usr/lib/x86_64-linux-gnu/libaio.so.1 ] &&
   [ -e /usr/lib/x86_64-linux-gnu/libaio.so.1t64 ]; then
  ln -s /usr/lib/x86_64-linux-gnu/libaio.so.1t64 "$probe/libaio.so.1"
fi
cat > "$probe/probe.yaml" <<'YAML'
http: {auto_start_http: false}
CFOptions:
  default:
    write_buffer_size: 17M
DBOptions:
  default:
    create_if_missing: true
    memtable_as_log_index: false
YAML
cat > "$probe/ToplingRuntimeProbe.java" <<'JAVA'
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Collectors;
import org.rocksdb.ColumnFamilyDescriptor;
import org.rocksdb.ColumnFamilyHandle;
import org.rocksdb.ColumnFamilyOptions;
import org.rocksdb.DBOptions;
import org.rocksdb.Options;
import org.rocksdb.RocksDB;

class ToplingRuntimeProbe {
    public static void main(String[] args) throws Exception {
        RocksDB.loadLibrary();
        Path database = Path.of(args[0]);
        byte[] family = "hugegraph-probe".getBytes(StandardCharsets.UTF_8);
        try (Options options = new Options().setCreateIfMissing(true);
             RocksDB db = RocksDB.open(options, database.toString());
             ColumnFamilyOptions cfOptions = new ColumnFamilyOptions();
             ColumnFamilyHandle cf = db.createColumnFamily(
                     new ColumnFamilyDescriptor(family, cfOptions))) {
            db.put(new byte[]{1}, new byte[]{2});
            db.put(cf, new byte[]{3}, new byte[]{4});
        }
        try (DBOptions options = new DBOptions();
             ColumnFamilyOptions cfOptions = new ColumnFamilyOptions()) {
            List<ColumnFamilyDescriptor> descriptors = Arrays.asList(
                    new ColumnFamilyDescriptor(RocksDB.DEFAULT_COLUMN_FAMILY, cfOptions),
                    new ColumnFamilyDescriptor(family, cfOptions));
            List<ColumnFamilyHandle> handles = new ArrayList<>();
            try (RocksDB db = RocksDB.open(options, database.toString(), descriptors, handles)) {
                try {
                    if (db.get(new byte[]{1})[0] != 2 ||
                        db.get(handles.get(1), new byte[]{3})[0] != 4) {
                        throw new IllegalStateException("JNI restart lost its column-family write");
                    }
                } finally {
                    handles.forEach(ColumnFamilyHandle::close);
                }
            }
        }
        Pattern expected = Pattern.compile("(?m)^\\s*write_buffer_size\\s*=\\s*17825792\\s*$");
        boolean configured = false;
        try (var paths = Files.list(database)) {
            List<Path> options = paths
                    .filter(p -> p.getFileName().toString().startsWith("OPTIONS-"))
                    .collect(Collectors.toList());
            for (Path path : options) {
                configured |= expected.matcher(Files.readString(path)).find();
            }
        }
        if (!configured) {
            throw new IllegalStateException("JNI does not apply TOPLINGDB_EASY_MIGRATE_CONF");
        }
    }
}
JAVA
LD_LIBRARY_PATH="$probe${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
LD_PRELOAD="$probe/librocksdbjni-linux64.so" \
TOPLINGDB_EASY_MIGRATE_CONF="$probe/probe.yaml" \
java --add-opens=java.base/java.nio=ALL-UNNAMED --source 11 \
    --class-path "$jar" "$probe/ToplingRuntimeProbe.java" "$probe/database"
