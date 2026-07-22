import json
import tempfile
import threading
import unittest
from pathlib import Path

from manageroo.artifacts import ArtifactStore
from manageroo.errors import SafetyError
from manageroo.util import atomic_write_text


class ArtifactConcurrencyTests(unittest.TestCase):
    def test_distinct_store_instances_serialize_complete_write_and_ledger_transactions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            first = ArtifactStore(root)
            second = ArtifactStore(root)

            first_writer_entered = threading.Event()
            release_first_writer = threading.Event()
            second_writer_entered = threading.Event()
            errors: list[BaseException] = []

            def first_writer(path: Path) -> None:
                atomic_write_text(path, "first\n")
                first_writer_entered.set()
                if not release_first_writer.wait(timeout=5):
                    raise TimeoutError("test did not release first artifact writer")

            def second_writer(path: Path) -> None:
                second_writer_entered.set()
                atomic_write_text(path, "second\n")

            def write_first() -> None:
                try:
                    first._write("first.txt", first_writer, lock=False)
                except BaseException as exc:
                    errors.append(exc)

            def write_second() -> None:
                try:
                    second._write("second.txt", second_writer, lock=False)
                except BaseException as exc:
                    errors.append(exc)

            first_thread = threading.Thread(target=write_first)
            second_thread = threading.Thread(target=write_second)
            first_thread.start()
            self.assertTrue(first_writer_entered.wait(timeout=5))
            second_thread.start()

            # The second store must not enter its file writer while the first store owns
            # the filesystem transaction lock. Without cross-instance locking, both could
            # read the same ledger snapshot and the last writer would drop one record.
            self.assertFalse(second_writer_entered.wait(timeout=0.2))
            release_first_writer.set()
            first_thread.join(timeout=5)
            second_thread.join(timeout=5)

            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertEqual(errors, [])
            self.assertTrue(second_writer_entered.is_set())
            ledger = json.loads((root / "artifact-ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(set(ledger["artifacts"]), {"first.txt", "second.txt"})

    def test_locked_artifact_cannot_be_replaced_by_another_store_instance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            first = ArtifactStore(root)
            second = ArtifactStore(root)
            first.write_text("locked.txt", "original\n", lock=True)

            with self.assertRaises(SafetyError):
                second.write_text("locked.txt", "replacement\n")

            self.assertEqual((root / "locked.txt").read_text(encoding="utf-8"), "original\n")
            first.verify_locked()


if __name__ == "__main__":
    unittest.main()
