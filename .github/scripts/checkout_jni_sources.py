#!/usr/bin/env python3
"""Checkout or verify the reviewed community JNI plugin source revisions."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / ".github/community-jni-sources.json"
DISABLED_REPOSITORIES = {"cspp-memtable", "topling-rocks", "topling-dcompact", "toplingdb-fs"}
# The pinned Makefiles generate these outside build/; never allow them before compilation.
GENERATED_OUTPUTS = {
    "sideplugin/topling-zip": {
        "3rdparty/base64/lib/arch/avx/codec.o",
        "3rdparty/base64/lib/arch/avx2/codec.o",
        "3rdparty/base64/lib/arch/generic/codec.o",
        "3rdparty/base64/lib/arch/neon32/codec.o",
        "3rdparty/base64/lib/arch/neon64/codec.o",
        "3rdparty/base64/lib/arch/sse41/codec.o",
        "3rdparty/base64/lib/arch/sse42/codec.o",
        "3rdparty/base64/lib/arch/ssse3/codec.o",
        "3rdparty/base64/lib/codec_choose.o",
        "3rdparty/base64/lib/config.h",
        "3rdparty/base64/lib/lib.o",
        "3rdparty/base64/lib/libbase64.o",
    },
    "sideplugin/topling-zip/boost-include": {
        "libs/config/checks/architecture/bin/gcc-13/debug/64.o",
        "libs/config/checks/architecture/bin/gcc-13/debug/x86.o",
    },
}


def git(directory, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(directory), *arguments], text=True
    ).rstrip("\n")


def load_lock(path):
    lock = json.loads(path.read_text())
    if lock.get("version") != 1 or not lock.get("repositories"):
        raise ValueError("Expected a version 1 source lock with repositories")
    seen = set()
    for entry in lock["repositories"]:
        relative = Path(entry["path"])
        if not relative.parts or relative.is_absolute() or ".." in relative.parts or \
           relative.parts[0] != "sideplugin":
            raise ValueError("Source paths must stay inside sideplugin/: " + str(relative))
        if len(relative.parts) < 2 or entry["path"] in seen:
            raise ValueError("Invalid or duplicate source path: " + str(relative))
        if not re.fullmatch(r"[0-9a-f]{40}", entry["commit"]):
            raise ValueError("Source revisions must be complete commit hashes")
        if entry["kind"] not in {"repository", "gitlink"} or not entry["url"]:
            raise ValueError("Expected a repository/gitlink and its origin URL")
        seen.add(entry["path"])
    return lock["repositories"]


def source_changes(directory, generated=()):
    if git(directory, "status", "--porcelain", "--untracked-files=no"):
        return "tracked changes"
    untracked = git(directory, "ls-files", "--others", "-z", "--",
                    ":(top,exclude)build", ":(top,exclude)build-ut")
    unexpected = [name for name in untracked.split("\0") if name and name not in generated]
    if unexpected:
        return "untracked source inputs (" + ", ".join(unexpected[:5]) + ")"
    for name in untracked.split("\0"):
        if name and ((directory / name).is_symlink() or not (directory / name).is_file()):
            return "non-regular generated output (" + name + ")"
    return ""


def verify_repository(root, entry, generated=()):
    directory = root / entry["path"]
    if not (directory / ".git").exists():
        raise RuntimeError("Missing locked repository: " + entry["path"])
    actual = git(directory, "rev-parse", "HEAD")
    if actual != entry["commit"]:
        raise RuntimeError(entry["path"] + ": expected " + entry["commit"] + ", found " + actual)
    if entry["kind"] == "gitlink":
        parent = Path(git(directory.parent, "rev-parse", "--show-toplevel"))
        tracked = git(parent, "ls-tree", "HEAD", directory.relative_to(parent).as_posix())
        if not tracked.startswith("160000 commit " + entry["commit"] + "\t"):
            raise RuntimeError("Source lock differs from its parent gitlink: " + entry["path"])
    changes = source_changes(directory, generated)
    if changes:
        raise RuntimeError("Locked source has " + changes + ": " + entry["path"])
    submodules = git(directory, "submodule", "status", "--recursive")
    if any(line.startswith(("+", "-", "U")) for line in submodules.splitlines()):
        raise RuntimeError("Submodule differs from its pinned gitlink: " + entry["path"])


def prepare(root, entries, checkout=False, after_build=False):
    if (root / "sideplugin/topling-core").exists():
        raise RuntimeError("Community builds must use public topling-zip, not private topling-core")
    for entry in entries:
        directory = root / entry["path"]
        if checkout and entry["kind"] == "repository":
            if directory.is_symlink() or directory.exists() and not (directory / ".git").exists():
                raise RuntimeError("Expected an independent Git checkout: " + entry["path"])
            if not directory.exists():
                directory.parent.mkdir(parents=True, exist_ok=True)
                subprocess.check_call(["git", "init", "--quiet", str(directory)])
                git(directory, "remote", "add", "origin", entry["url"])
            if source_changes(directory):
                raise RuntimeError("Refusing to change a modified source checkout: " +
                                   entry["path"])
            fetch = ["fetch", "origin", entry["commit"]]
            if git(directory, "rev-parse", "--is-shallow-repository") == "true":
                fetch.insert(1, "--unshallow")
            git(directory, *fetch)
            git(directory, "checkout", "--detach", entry["commit"])
            git(directory, "submodule", "update", "--init", "--recursive")
        generated = GENERATED_OUTPUTS.get(entry["path"], ()) if after_build else ()
        verify_repository(root, entry, generated)
    allowed = {Path(entry["path"]).parts[1] for entry in entries} | DISABLED_REPOSITORIES
    for directory in (root / "sideplugin").iterdir():
        if (directory / ".git").exists() and directory.name not in allowed:
            raise RuntimeError("Unlisted plugin repository: " + directory.name)


def build_context(root, entries):
    return {
        "version": 1,
        "source_revision": git(root, "rev-parse", "HEAD"),
        "source_lock": hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
    }


def record_clean_start(root, entries, receipt):
    prepare(root, entries)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(build_context(root, entries), sort_keys=True) + "\n")


def verify_built(root, entries, receipt):
    if not receipt.is_file() or json.loads(receipt.read_text()) != build_context(root, entries):
        raise RuntimeError("Missing or stale clean-start receipt; verify pristine sources first")
    prepare(root, entries, after_build=True)
    outputs = []
    for entry in entries:
        for name in sorted(GENERATED_OUTPUTS.get(entry["path"], ())):
            path = root / entry["path"] / name
            if path.is_file():
                outputs.append((entry["path"] + "/" + name,
                                hashlib.sha256(path.read_bytes()).hexdigest()))
    return outputs


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("checkout", "verify", "verify-built"))
    parser.add_argument("--receipt", type=Path)
    arguments = parser.parse_args()
    repositories = load_lock(LOCK)
    outputs = []
    if arguments.mode == "verify-built":
        if arguments.receipt is None:
            parser.error("verify-built requires --receipt from a successful prebuild verify")
        outputs = verify_built(ROOT, repositories, arguments.receipt)
    elif arguments.mode == "verify" and arguments.receipt is not None:
        record_clean_start(ROOT, repositories, arguments.receipt)
    else:
        prepare(ROOT, repositories, checkout=arguments.mode == "checkout")
    print("community_source_lock_sha256=" + hashlib.sha256(LOCK.read_bytes()).hexdigest())
    for repository in repositories:
        print("locked_source=" + repository["path"] + " " + repository["commit"])
    if arguments.mode == "verify-built":
        print("source_validation=clean_before_build,tracked_sources_unchanged_after_build")
        for path, digest in outputs:
            print("generated_output_sha256=" + digest + " " + path)
