#!/usr/bin/env python3
"""Attach the selected native sources' license texts to the unsigned JNI JAR."""

import argparse
import hashlib
import os
from pathlib import Path
import re
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[2]
LICENSE_NAME = re.compile(r"^(LICENSE|LICENCE|COPYING|NOTICE)([._-].*)?$", re.I)
SKIP_DIRS = {".git", "build", "build-ut", "__pycache__"}
SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".h", ".hpp"}
EMBEDDED_LICENSES = {
    "sideplugin/rockside/src/topling/web/civetweb.c",
    "sideplugin/topling-zip/src/terark/json.hpp",
}


def collect_source_notices(directory, entries):
    for current, directories, filenames in os.walk(directory):
        directories[:] = sorted(d for d in directories if d not in SKIP_DIRS)
        for name in sorted(filenames):
            source = Path(current) / name
            if source.is_symlink():
                continue
            relative = source.relative_to(ROOT).as_posix()
            if LICENSE_NAME.fullmatch(name) or name.lower() == "copyright":
                entries[relative] = source.read_bytes()
            elif source.suffix in SOURCE_SUFFIXES and (
                relative in EMBEDDED_LICENSES or "/3rdparty/zstd/" in relative
            ):
                text = source.read_text(errors="replace")
                notices = []
                for match in re.finditer(r"/\*.*?\*/", text, re.S):
                    block = match.group()
                    normalized = " ".join(block.lower().replace("*", " ").split())
                    is_grant = any(marker in normalized for marker in (
                        "permission is hereby granted",
                        "redistribution and use in source and binary forms",
                        "boost software license",
                    ))
                    # Preserve bundled Zstd copyright/alternative-license notices too.
                    is_zstd_notice = "/3rdparty/zstd/" in relative and \
                        "copyright" in normalized and match.start() < 100
                    if is_grant or is_zstd_notice:
                        notices.append(block)
                if notices:
                    entries[relative + ".license.txt"] = (
                        "Source: " + relative + "\n\n" + "\n\n".join(notices) + "\n"
                    ).encode()


def bundle(jar, provenance, features):
    entries = {}
    for name in ("LICENSE.Apache", "LICENSE.leveldb"):
        entries[name] = (ROOT / name).read_bytes()
    for source in ROOT.glob("NOTICE*"):
        if source.is_file():
            entries[source.name] = source.read_bytes()
    repositories = ["rockside", "topling-zip", "cspp-wbwi", "topling-sst",
                    "topling-zip_table_reader"]
    if features == "full":
        repositories += ["topling-rocks", "cspp-memtable", "topling-dcompact"]
    for repository in repositories:
        directory = ROOT / "sideplugin" / repository
        if directory.is_dir():
            collect_source_notices(directory, entries)
    required = [
        "sideplugin/rockside/LICENSE",
        "sideplugin/rockside/3rdparty/rapidyaml/LICENSE.txt",
        "sideplugin/rockside/3rdparty/rapidyaml/ext/c4core/LICENSE.txt",
        "sideplugin/topling-zip/LICENSE",
        "sideplugin/topling-zip/3rdparty/base64/LICENSE",
        "sideplugin/topling-zip/boost-include/LICENSE_1_0.txt",
        "sideplugin/rockside/src/topling/web/civetweb.c.license.txt",
        "sideplugin/topling-zip/src/terark/json.hpp.license.txt",
        "sideplugin/topling-zip/3rdparty/zstd/zstd/dictBuilder/divsufsort.c.license.txt",
        "sideplugin/topling-zip/3rdparty/zstd/zstd/common/xxhash.c.license.txt",
    ]
    for name in required:
        if name not in entries:
            raise RuntimeError("Missing native source license/notice: " + name)
    supplement = ".github/licenses/zstd-1.4.5-LICENSE"
    entries[supplement] = (ROOT / supplement).read_bytes()
    fast_float = "sideplugin/rockside/3rdparty/rapidyaml/ext/c4core/src/c4/ext/fast_float/"
    for name in ("AUTHORS", "CONTRIBUTORS"):
        entries[fast_float + name] = (ROOT / (fast_float + name)).read_bytes()
    entries["README.txt"] = (
        "Native JNI license and notice texts, preserving source-relative paths.\n"
        "The RocksDB core uses the Apache-2.0 alternative; LevelDB retains its BSD terms.\n"
        "*.license.txt files preserve grants/copyright notices embedded in source comments.\n"
        "The vendored Zstd 1.4.5 source omits its root LICENSE; its BSD alternative is\n"
        "supplied from https://github.com/facebook/zstd/blob/v1.4.5/LICENSE\n"
        "(Git blob a793a802892567f17d464a831e2e531dc8833f55).\n"
        "The source/build selection is recorded in META-INF/topling-build-info.txt.\n"
        "These notices do not grant rights to optional proprietary/trial components.\n"
    ).encode()
    inventory = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n"
                        for name, data in sorted(entries.items()))
    entries["manifest.sha256"] = inventory.encode()
    with tempfile.NamedTemporaryFile(dir=jar.parent, suffix=".jar", delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        with zipfile.ZipFile(jar) as original, zipfile.ZipFile(temporary, "w") as output:
            for info in original.infolist():
                if info.filename.startswith("META-INF/licenses/") or \
                   info.filename == "META-INF/topling-build-info.txt":
                    continue
                if re.fullmatch(r"META-INF/[^/]+\.(SF|RSA|DSA)", info.filename, re.I):
                    raise RuntimeError("Expected an unsigned source-built JNI JAR")
                output.writestr(info, original.read(info))
            for name, data in sorted(entries.items()):
                output.writestr("META-INF/licenses/" + name, data, zipfile.ZIP_DEFLATED)
            output.writestr("META-INF/topling-build-info.txt", provenance.read_bytes(),
                            zipfile.ZIP_DEFLATED)
        temporary.chmod(jar.stat().st_mode & 0o777)
        temporary.replace(jar)
    finally:
        temporary.unlink(missing_ok=True)
    print("Embedded", len(entries), "license/notice files in", jar)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jar", type=Path)
    parser.add_argument("provenance", type=Path)
    parser.add_argument("--native-features", choices=("community", "full"), default="community")
    arguments = parser.parse_args()
    bundle(arguments.jar.resolve(), arguments.provenance, arguments.native_features)
