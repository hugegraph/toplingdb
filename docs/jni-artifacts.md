# JNI artifacts for HugeGraph containers

The `build topling-jni` workflow builds Linux amd64 JNI on Ubuntu 24.04 with
GCC 13. It always uploads a run-specific `topling-jni-linux-amd64-<source SHA>`
Actions artifact, including when `deploy_maven=false`. The archive contains:

- `rocksdbjni-8.10.2-linux64.jar` (the version follows `build_tools/version.sh`);
- the JAR's SHA-256 checksum file;
- `build-info.txt`, recording the source revision, build run, compiler, flags and
  the revisions of the SidePlugin repositories used by the build.

The build enables `ROCKSDB_DYNAMIC_CREATE_CF`, required by HugeGraph backend
initialization. Before upload, the workflow loads the native JNI, applies a configuration through
`TOPLINGDB_EASY_MIGRATE_CONF`, creates a column family, writes to both column
families in a disposable database and reopens them. It checks
that the configured write-buffer size was persisted. This is a runtime capability
check; it does not certify existing database migration or every production option.

For a public download suitable for Docker builds, manually dispatch the workflow
on the desired source ref with `publish_release=true`. Maven publication is
independent and can be disabled. After the complete build passes, a separate job
publishes the same verified payload under the tag `jni-<full source SHA>`:

```text
https://github.com/hugegraph/toplingdb/releases/download/jni-<full source SHA>/rocksdbjni-8.10.2-linux64.jar
```

The job refuses to replace an existing release. Pin the JAR URL and its SHA-256 in
the image build; avoid moving branch URLs and Maven snapshot metadata. Download
the matching `.sha256` file and verify it before using the JAR:

```bash
sha256sum --check rocksdbjni-8.10.2-linux64.jar.sha256
```

The build includes the Topling plugins selected by the normal Makefile, which may
download precompiled trial components. The build manifest records their revisions;
it does not extend any trial license. The current native runtime is Linux amd64
and requires an AVX2/BMI2-capable CPU, glibc 2.38 or newer, and its native runtime
dependencies. Use HugeGraph's `prepare-topling.sh` on the final image base to verify
the JAR checksum, ELF architecture, native dependencies and Java 17 configuration
entry point before publishing an image. On Ubuntu, the preparation script handles
the libaio t64 soname within the prepared runtime directory.
