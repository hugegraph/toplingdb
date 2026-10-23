#!/usr/bin/env python3
"""Exercise the dependency lock against real local Git repositories."""

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    "checkout_jni_sources", Path(__file__).with_name("checkout_jni_sources.py")
)
SOURCES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SOURCES)


class SourceLockTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.origin = self.root / "origin"
        subprocess.check_call(["git", "init", "--quiet", str(self.origin)])
        SOURCES.git(self.origin, "config", "user.name", "Source lock test")
        SOURCES.git(self.origin, "config", "user.email", "source-lock@example.invalid")
        self.first = self.commit("reviewed content")
        self.second = self.commit("new branch head")
        self.entry = {"path": "sideplugin/demo", "url": str(self.origin),
                      "commit": self.first, "kind": "repository"}
        self.checkout = self.root / self.entry["path"]

    def commit(self, content):
        (self.origin / "source.txt").write_text(content)
        SOURCES.git(self.origin, "add", "source.txt")
        SOURCES.git(self.origin, "commit", "--quiet", "-m", content)
        return SOURCES.git(self.origin, "rev-parse", "HEAD")

    def test_checkout_uses_reviewed_commit_and_detects_a_new_head(self):
        SOURCES.prepare(self.root, [self.entry], checkout=True)
        self.assertEqual((self.checkout / "source.txt").read_text(), "reviewed content")
        SOURCES.git(self.checkout, "fetch", "--depth=1", "origin", self.second)
        SOURCES.git(self.checkout, "checkout", "--detach", self.second)
        with self.assertRaisesRegex(RuntimeError, "expected .* found"):
            SOURCES.prepare(self.root, [self.entry])

    def test_dirty_checkout_is_rejected_without_discarding_changes(self):
        SOURCES.prepare(self.root, [self.entry], checkout=True)
        (self.checkout / "source.txt").write_text("local modification")
        with self.assertRaisesRegex(RuntimeError, "tracked changes"):
            SOURCES.prepare(self.root, [self.entry])
        with self.assertRaisesRegex(RuntimeError, "Refusing to change"):
            SOURCES.prepare(self.root, [self.entry], checkout=True)
        self.assertEqual((self.checkout / "source.txt").read_text(), "local modification")

    def test_existing_directory_must_be_an_independent_repository(self):
        self.checkout.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, "independent Git checkout"):
            SOURCES.prepare(self.root, [self.entry], checkout=True)

    def test_untracked_source_is_rejected_but_generated_build_files_are_allowed(self):
        SOURCES.prepare(self.root, [self.entry], checkout=True)
        (self.checkout / "build").mkdir()
        (self.checkout / "build/generated-version.cc").write_text("generated version")
        SOURCES.prepare(self.root, [self.entry])
        (self.checkout / "extra.cc").write_text("unexpected wildcard input")
        with self.assertRaisesRegex(RuntimeError, "untracked source inputs"):
            SOURCES.prepare(self.root, [self.entry])
        with self.assertRaisesRegex(RuntimeError, "Refusing to change"):
            SOURCES.prepare(self.root, [self.entry], checkout=True)

    def test_submodule_lock_must_match_its_parent_gitlink(self):
        SOURCES.prepare(self.root, [self.entry], checkout=True)
        subprocess.check_call(["git", "init", "--quiet", str(self.root)])
        SOURCES.git(self.root, "config", "user.name", "Source lock test")
        SOURCES.git(self.root, "config", "user.email", "source-lock@example.invalid")
        SOURCES.git(self.root, "update-index", "--add", "--cacheinfo",
                    "160000," + self.second + "," + self.entry["path"])
        SOURCES.git(self.root, "commit", "--quiet", "-m", "parent uses another revision")
        with self.assertRaisesRegex(RuntimeError, "parent gitlink"):
            SOURCES.prepare(self.root, [dict(self.entry, kind="gitlink")])

    def test_incomplete_revision_is_rejected(self):
        lock = self.root / "sources.json"
        lock.write_text(json.dumps({"version": 1, "repositories": [
            dict(self.entry, commit=self.first[:12])
        ]}))
        with self.assertRaisesRegex(ValueError, "complete commit hashes"):
            SOURCES.load_lock(lock)


if __name__ == "__main__":
    unittest.main()
