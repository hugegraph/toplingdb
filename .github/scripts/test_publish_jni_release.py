#!/usr/bin/env python3
"""Run the real release script with a local fake gh; no network or publication occurs."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("publish_jni_release.sh")
SOURCE_SHA = "a" * 40
TAG_OBJECT = "b" * 40


class PublishReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        binary = self.root / "bin"
        binary.mkdir()
        fake = binary / "gh"
        fake.write_text("""#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['GH_TEST_CALLS']).open('a') as calls:
    calls.write(json.dumps(args) + '\\n')
state = json.loads(Path(os.environ['GH_TEST_STATE']).read_text())
if args[:2] == ['release', 'view']:
    sys.exit(0 if state.get('existing') else 1)
if args[0] == 'api':
    print(json.dumps(state['responses'][args[1]]))
elif args[:2] != ['release', 'create']:
    sys.exit('unexpected gh call')
""")
        fake.chmod(0o755)
        self.calls = self.root / "calls.jsonl"
        self.state = self.root / "state.json"
        self.environment = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                                GH_REPO="example/toplingdb", SOURCE_SHA=SOURCE_SHA,
                                NATIVE_FEATURES="community", GH_TEST_CALLS=str(self.calls),
                                GH_TEST_STATE=str(self.state))
        payload = b"fixture JNI payload"
        (self.root / "runtime.jar").write_bytes(payload)
        (self.root / "runtime.jar.sha256").write_text(
            hashlib.sha256(payload).hexdigest() + "  runtime.jar\n"
        )
        (self.root / "build-info.txt").write_text("fixture provenance\n")

    def run_release(self, target=SOURCE_SHA, annotated=False, existing=False):
        endpoint = "repos/example/toplingdb/git/ref/tags/jni-" + SOURCE_SHA
        responses = {endpoint: {"object": {"type": "commit", "sha": target}}}
        if annotated:
            responses[endpoint] = {"object": {"type": "tag", "sha": TAG_OBJECT}}
            responses["repos/example/toplingdb/git/tags/" + TAG_OBJECT] = {
                "object": {"type": "commit", "sha": target}
            }
        self.state.write_text(json.dumps({"responses": responses, "existing": existing}))
        result = subprocess.run(["bash", str(SCRIPT)], cwd=self.root, env=self.environment,
                                text=True, capture_output=True)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] \
            if self.calls.exists() else []
        creates = [call for call in calls if call[:2] == ["release", "create"]]
        return result, creates

    def test_lightweight_tag_at_source_commit_can_publish(self):
        result, creates = self.run_release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(creates), 1)
        self.assertIn("--verify-tag", creates[0])

    def test_wrong_lightweight_tag_is_rejected_before_create(self):
        result, creates = self.run_release(target="c" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected " + SOURCE_SHA, result.stderr)
        self.assertFalse(creates)

    def test_annotated_tag_is_peeled_to_its_commit(self):
        result, creates = self.run_release(annotated=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(creates), 1)

    def test_wrong_annotated_tag_is_rejected_before_create(self):
        result, creates = self.run_release(target="c" * 40, annotated=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(creates)

    def test_existing_release_remains_immutable(self):
        result, creates = self.run_release(existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refusing to replace", result.stderr)
        self.assertFalse(creates)

    def test_unqualified_full_cannot_publish(self):
        self.environment["NATIVE_FEATURES"] = "full"
        result, creates = self.run_release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("awaits full qualification", result.stderr)
        self.assertFalse(creates)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
