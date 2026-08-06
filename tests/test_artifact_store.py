import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from tests.support import symlink_or_skip

from manageroo.artifacts import ArtifactStore
from manageroo.errors import SafetyError


class ArtifactStoreTests(unittest.TestCase):
    def test_symlinked_transaction_lock_cannot_modify_external_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "artifacts"
            external = base / "external-lock"
            reclaim = external / "reclaim"
            root.mkdir()
            reclaim.mkdir(parents=True)
            sentinel = reclaim / "sentinel.txt"
            sentinel.write_text("external\n", encoding="utf-8")
            stale_time = 1
            os.utime(reclaim, (stale_time, stale_time))
            os.utime(external, (stale_time, stale_time))
            symlink_or_skip(
                self,
                external,
                root / ".artifact-ledger.lock",
                target_is_directory=True,
            )

            with self.assertRaises(SafetyError):
                ArtifactStore(root)

            self.assertTrue(reclaim.is_dir())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "external\n")
            self.assertEqual([path.name for path in external.iterdir()], ["reclaim"])

    def test_parent_swap_during_creation_never_writes_outside_store(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "artifacts"
            outside = base / "outside"
            outside.mkdir()
            store = ArtifactStore(root)
            parent = root / "nested"
            real_mkdir = os.mkdir
            swapped = False

            def swap_then_mkdir(path, *args, **kwargs):
                nonlocal swapped
                if Path(path).name == "nested" and not swapped:
                    symlink_or_skip(self, outside, parent, target_is_directory=True)
                    swapped = True
                return real_mkdir(path, *args, **kwargs)

            with mock.patch(
                "manageroo.artifacts.os.mkdir",
                side_effect=swap_then_mkdir,
            ):
                with self.assertRaises(SafetyError):
                    store.write_text("nested/report.txt", "contained\n")

            self.assertTrue(swapped)
            self.assertFalse((outside / "report.txt").exists())

    def test_parent_swap_during_replacement_never_writes_outside_store(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "artifacts"
            parent = root / "nested"
            outside = base / "outside"
            parent.mkdir(parents=True)
            outside.mkdir()
            store = ArtifactStore(root)
            moved = base / "nested-pinned"
            real_replace = os.replace
            swapped = False

            def swap_then_replace(source, destination, *args, **kwargs):
                nonlocal swapped
                if Path(destination).name == "report.txt" and not swapped:
                    parent.rename(moved)
                    symlink_or_skip(self, outside, parent, target_is_directory=True)
                    swapped = True
                return real_replace(source, destination, *args, **kwargs)

            with mock.patch(
                "manageroo.artifacts.os.replace",
                side_effect=swap_then_replace,
            ):
                with self.assertRaises(SafetyError):
                    store.write_text("nested/report.txt", "contained\n")

            self.assertTrue(swapped)
            self.assertFalse((outside / "report.txt").exists())
            self.assertFalse((moved / "report.txt").exists())

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
