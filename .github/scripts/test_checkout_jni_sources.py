#!/usr/bin/env python3
"""Exercise the dependency lock against real local Git repositories."""

import importlib.util
import hashlib
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
        subprocess.check_call(["git", "init", "--quiet", str(self.root)])
        SOURCES.git(self.root, "config", "user.name", "Source lock test")
        SOURCES.git(self.root, "config", "user.email", "source-lock@example.invalid")
        (self.root / "README").write_text("fixture build root")
        SOURCES.git(self.root, "add", "README")
        SOURCES.git(self.root, "commit", "--quiet", "-m", "fixture build root")
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

    def checkout_with_ignore(self, pattern, path="sideplugin/demo"):
        (self.origin / ".gitignore").write_text(pattern)
        SOURCES.git(self.origin, "add", ".gitignore")
        SOURCES.git(self.origin, "commit", "--quiet", "-m", "ignore generated files")
        entry = dict(self.entry, path=path, commit=SOURCES.git(self.origin, "rev-parse", "HEAD"))
        SOURCES.prepare(self.root, [entry], checkout=True)
        return entry, self.root / path

    def assert_ignored_input_rejected(self, entry, name):
        directory = self.root / entry["path"]
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("untrusted ignored build input")
        self.assertEqual(SOURCES.git(directory, "check-ignore", name), name)
        self.assertEqual(SOURCES.git(directory, "status", "--porcelain",
                                     "--untracked-files=no"), "")
        with self.assertRaisesRegex(RuntimeError, "untracked source inputs"):
            SOURCES.prepare(self.root, [entry])
        with self.assertRaisesRegex(RuntimeError, "Refusing to change"):
            SOURCES.prepare(self.root, [entry], checkout=True)
        path.unlink()

    def test_repository_ignored_source_header_and_library_are_rejected(self):
        entry, directory = self.checkout_with_ignore("*.cc\n*.h\n*.a\n")
        for name in ("extra.cc", "included.h", "foreign.a"):
            with self.subTest(name=name):
                self.assert_ignored_input_rejected(entry, name)

    def test_info_exclude_cannot_hide_an_ignored_source(self):
        SOURCES.prepare(self.root, [self.entry], checkout=True)
        (self.checkout / ".git/info/exclude").write_text("extra.cc\n")
        self.assert_ignored_input_rejected(self.entry, "extra.cc")

    def test_external_excludes_file_cannot_hide_an_ignored_library(self):
        SOURCES.prepare(self.root, [self.entry], checkout=True)
        excludes = self.root / "global-ignore"
        excludes.write_text("foreign.so\n")
        SOURCES.git(self.checkout, "config", "core.excludesFile", str(excludes))
        self.assert_ignored_input_rejected(self.entry, "foreign.so")

    def test_known_generated_file_is_rejected_before_clean_start(self):
        entry, directory = self.checkout_with_ignore("*.h\n*.o\n", "sideplugin/topling-zip")
        receipt = self.root / "build/clean-start.json"
        for name in ("3rdparty/base64/lib/config.h", "3rdparty/base64/lib/libbase64.o",
                     "3rdparty/base64/lib/arch/avx2/codec.o"):
            with self.subTest(name=name):
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("pre-existing ignored configuration or library")
                self.assertEqual(SOURCES.git(directory, "check-ignore", name), name)
                with self.assertRaisesRegex(RuntimeError, "untracked source inputs"):
                    SOURCES.record_clean_start(self.root, [entry], receipt)
                self.assertFalse(receipt.exists())
                path.unlink()

    def test_postbuild_outputs_require_clean_start_and_are_hashed(self):
        entry, directory = self.checkout_with_ignore("*.h\n*.a\n", "sideplugin/topling-zip")
        receipt = self.root / "build/clean-start.json"
        with self.assertRaisesRegex(RuntimeError, "Missing or stale"):
            SOURCES.verify_built(self.root, [entry], receipt)
        SOURCES.record_clean_start(self.root, [entry], receipt)
        name = "3rdparty/base64/lib/config.h"
        path = directory / name
        path.parent.mkdir(parents=True)
        path.write_text("configuration generated after clean start")
        outputs = SOURCES.verify_built(self.root, [entry], receipt)
        self.assertEqual(outputs, [(entry["path"] + "/" + name,
                                    hashlib.sha256(path.read_bytes()).hexdigest())])
        extra = directory / "foreign.a"
        extra.write_text("not a declared build output")
        self.assertEqual(SOURCES.git(directory, "check-ignore", "foreign.a"), "foreign.a")
        with self.assertRaisesRegex(RuntimeError, "untracked source inputs"):
            SOURCES.verify_built(self.root, [entry], receipt)
        extra.unlink()
        stale = json.loads(receipt.read_text())
        stale["run_id"] = "different run"
        receipt.write_text(json.dumps(stale))
        with self.assertRaisesRegex(RuntimeError, "Missing or stale"):
            SOURCES.verify_built(self.root, [entry], receipt)


if __name__ == "__main__":
    unittest.main()
