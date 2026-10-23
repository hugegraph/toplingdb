# JNI artifacts for HugeGraph containers

The `build topling-jni` workflow builds Linux amd64 JNI on Ubuntu 24.04 with
GCC 13. It defaults to `native_features=community`, which consistently sets
`WITH_TOPLING_ROCKS=0 WITH_CSPP_MEMTABLE=0 WITH_TOPLING_DCOMPACT=0` in every Make invocation.
This builds
the public runtime without downloading the optional ToplingZip Builder/CSPP
MemTable trial objects. It always uploads a run-specific
`topling-jni-linux-amd64-<source SHA>`
Actions artifact, including when `deploy_maven=false`. The archive contains:

- `rocksdbjni-8.10.2-linux64.jar` (the version follows `build_tools/version.sh`);
- the JAR's SHA-256 checksum file;
- `build-info.txt`, recording the source revision, build run, compiler, flags and
  the revisions of the SidePlugin repositories used by the build.

The JAR embeds the selected source repositories' license/notice texts under
`META-INF/licenses/`, preserving their source paths. It also includes source-embedded
MIT/BSD notices, the vendored Zstd 1.4.5 BSD license, a license checksum inventory,
and `META-INF/topling-build-info.txt` matching the external build manifest. These
entries are installed before the JAR's final SHA-256 is calculated. The community
preset excludes dcompact, whose current source repository has no license grant.

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

Alternatively, push a `jni-build-*` tag pointing to a reviewed source commit. This
triggers the same community build and publishes its immutable `jni-<source SHA>`
release after the JNI checks pass; Maven publication and JMH remain disabled:

```bash
source_sha="$(git rev-parse HEAD)"
git tag "jni-build-${source_sha}" "$source_sha"
git push origin "jni-build-${source_sha}"
```

The manual `native_features=full` choice enables the normal Makefile's optional
ToplingZip Builder/CSPP MemTable trial components. Its release uses the distinct
tag `jni-<source SHA>-full`, so it cannot replace the community artifact. The build
manifest records the selected feature preset and plugin revisions; it does not
extend any trial license. Use a configuration matching the selected features:
community images use public SkipList/BlockBasedTable factories; CSPP configurations
require an appropriate full artifact.

The current native runtime is Linux amd64
and requires an AVX2/BMI2-capable CPU, glibc 2.38 or newer, and its native runtime
dependencies. Use HugeGraph's `prepare-topling.sh` on the final image base to verify
the JAR checksum, ELF architecture, native dependencies and Java 17 configuration
entry point before publishing an image. On Ubuntu, the preparation script handles
the libaio t64 soname within the prepared runtime directory.
