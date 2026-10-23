#!/usr/bin/env python3
"""Checkout or verify the reviewed community JNI plugin source revisions."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / ".github/community-jni-sources.json"
DISABLED_REPOSITORIES = {"cspp-memtable", "topling-rocks", "topling-dcompact", "toplingdb-fs"}


def git(directory, *arguments):
    return subprocess.check_output(
        ["git", "-C", str(directory), *arguments], text=True
    ).strip()


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


def source_changes(directory):
    if git(directory, "status", "--porcelain", "--untracked-files=no"):
        return "tracked changes"
    untracked = git(directory, "ls-files", "--others", "--exclude-standard", "-z")
    unexpected = [name for name in untracked.split("\0") if name and
                  Path(name).parts[0] not in {"build", "build-ut"}]
    if unexpected:
        return "untracked source inputs (" + ", ".join(unexpected[:5]) + ")"
    return ""


def verify_repository(root, entry):
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
    changes = source_changes(directory)
    if changes:
        raise RuntimeError("Locked source has " + changes + ": " + entry["path"])
    submodules = git(directory, "submodule", "status", "--recursive")
    if any(line.startswith(("+", "-", "U")) for line in submodules.splitlines()):
        raise RuntimeError("Submodule differs from its pinned gitlink: " + entry["path"])


def prepare(root, entries, checkout=False):
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
        verify_repository(root, entry)
    allowed = {Path(entry["path"]).parts[1] for entry in entries} | DISABLED_REPOSITORIES
    for directory in (root / "sideplugin").iterdir():
        if (directory / ".git").exists() and directory.name not in allowed:
            raise RuntimeError("Unlisted plugin repository: " + directory.name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("checkout", "verify"))
    arguments = parser.parse_args()
    repositories = load_lock(LOCK)
    prepare(ROOT, repositories, checkout=arguments.mode == "checkout")
    print("community_source_lock_sha256=" + hashlib.sha256(LOCK.read_bytes()).hexdigest())
    for repository in repositories:
        print("locked_source=" + repository["path"] + " " + repository["commit"])
