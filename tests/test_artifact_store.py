import json
import tempfile
import threading
import unittest
from pathlib import Path

from tests.support import symlink_or_skip

from manageroo.artifacts import ArtifactStore
from manageroo.errors import SafetyError


class ArtifactStoreTests(unittest.TestCase):
    def test_locked_artifact_cannot_be_overwritten_through_symlink_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            store = ArtifactStore(root)
            locked_path = root / "locked.txt"
            store.write_text("locked.txt", "original\n", lock=True)
            ledger_before = (root / "artifact-ledger.json").read_bytes()
            symlink_or_skip(self, "locked.txt", root / "alias.txt")

            with self.assertRaisesRegex(SafetyError, "symlink"):
                store.write_text("alias.txt", "replacement\n")

            self.assertEqual(locked_path.read_bytes(), b"original\n")
            self.assertEqual((root / "artifact-ledger.json").read_bytes(), ledger_before)

    def test_reserved_internal_paths_cannot_weaken_locked_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            store = ArtifactStore(root)
            store.write_text("proof.txt", "original\n", lock=True)
            ledger_before = (root / "artifact-ledger.json").read_bytes()

            reserved_writes = (
                (store.write_json, "artifact-ledger.json", {"artifacts": {}}),
                (store.write_text, ".artifact-ledger.lock", "replacement\n"),
                (store.write_text, ".artifact-ledger.lock/child", "temporary\n"),
                (store.write_text, ".artifact-ledger.advisory.lock", "replacement\n"),
                (store.write_text, ".artifact-ledger.transaction", "replacement\n"),
                (store.write_text, ".artifact-ledger.transaction/child", "temporary\n"),
            )
            for writer, relative, value in reserved_writes:
                with self.subTest(relative=relative), self.assertRaises(SafetyError):
                    writer(relative, value)

            self.assertEqual((root / "artifact-ledger.json").read_bytes(), ledger_before)
            self.assertEqual((root / "proof.txt").read_text(encoding="utf-8"), "original\n")
            with self.assertRaises(SafetyError):
                store.write_text("proof.txt", "replacement\n")
            store.verify_locked()

    def test_two_store_instances_preserve_distinct_concurrent_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            first = ArtifactStore(root)
            second = ArtifactStore(root)
            start = threading.Barrier(3)
            errors = []

            def write_one():
                try:
                    start.wait()
                    first.write_json("one.json", {"value": 1})
                except Exception as exc:
                    errors.append(exc)

            def write_two():
                try:
                    start.wait()
                    second.write_json("two.json", {"value": 2})
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=write_one), threading.Thread(target=write_two)]
            for thread in threads:
                thread.start()
            start.wait()
            for thread in threads:
                thread.join(timeout=10)

            self.assertEqual(errors, [])
            ledger = json.loads((root / "artifact-ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(set(ledger["artifacts"]), {"one.json", "two.json"})

    def test_locked_record_is_enforced_across_store_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            first = ArtifactStore(root)
            second = ArtifactStore(root)
            first.write_text("proof.txt", "first\n", lock=True)
            with self.assertRaises(SafetyError):
                second.write_text("proof.txt", "second\n")
            self.assertEqual((root / "proof.txt").read_text(encoding="utf-8"), "first\n")
            second.verify_locked()


if __name__ == "__main__":
    unittest.main()
