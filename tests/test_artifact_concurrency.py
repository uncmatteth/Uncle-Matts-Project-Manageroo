import json
import multiprocessing
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from manageroo.artifacts import ArtifactStore
from manageroo.errors import SafetyError
from manageroo.util import atomic_write_text


class ArtifactConcurrencyTests(unittest.TestCase):
    def test_crashed_reclaimer_claim_does_not_permanently_wedge_store(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            store = ArtifactStore(root)
            lock_path = root / ".artifact-ledger.lock"
            lock_path.mkdir()
            (lock_path / "owner").write_text(
                "pid=99999999\ntoken=abandoned-lock\n",
                encoding="utf-8",
            )
            claim_path = lock_path / "reclaim"
            claim_path.mkdir()
            (claim_path / "owner").write_text(
                "pid=99999999\ntoken=abandoned-reclaimer\n",
                encoding="utf-8",
            )
            stale_time = time.time() - 10
            os.utime(lock_path, (stale_time, stale_time))
            os.utime(claim_path, (stale_time, stale_time))

            store.write_text("recovered.txt", "ok\n")

            self.assertEqual((root / "recovered.txt").read_text(encoding="utf-8"), "ok\n")
            self.assertFalse(lock_path.exists())

    def test_stale_lock_recovery_does_not_require_hard_link_support(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            store = ArtifactStore(root)
            lock_path = root / ".artifact-ledger.lock"
            lock_path.mkdir()
            (lock_path / "owner").write_text(
                "pid=99999999\ntoken=abandoned-lock\n",
                encoding="utf-8",
            )
            stale_time = time.time() - 10
            os.utime(lock_path, (stale_time, stale_time))

            with mock.patch("manageroo.artifacts.os.link", side_effect=OSError("unsupported")):
                store.write_text("portable.txt", "ok\n")

            self.assertEqual((root / "portable.txt").read_text(encoding="utf-8"), "ok\n")

    def test_release_does_not_remove_replacement_lock_from_same_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            store = ArtifactStore(root)
            lock_path = root / ".artifact-ledger.lock"

            with store._transaction_lock():
                shutil.rmtree(lock_path)
                lock_path.mkdir()
                (lock_path / "owner").write_text(
                    f"pid={os.getpid()}\ntoken=replacement\n",
                    encoding="utf-8",
                )

            self.assertTrue(lock_path.is_dir())
            self.assertIn("token=replacement", (lock_path / "owner").read_text(encoding="utf-8"))

    def test_competing_reclaimers_never_overlap(self):
        try:
            process_context = multiprocessing.get_context("fork")
        except ValueError:
            self.skipTest("coordinated lock-reclamation test requires fork")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            first = ArtifactStore(root)
            second = ArtifactStore(root)
            lock_path = root / ".artifact-ledger.lock"
            lock_path.mkdir()
            (lock_path / "owner").write_text("unknown-owner\n", encoding="utf-8")
            stale_time = time.time() - 10
            os.utime(lock_path, (stale_time, stale_time))

            real_rmtree = shutil.rmtree
            removal_guard = process_context.Lock()
            removal_count = process_context.Value("i", 0)
            second_reclaimer_ready = process_context.Event()
            stale_lock_removed = process_context.Event()
            first_critical_section = process_context.Event()
            release_first = process_context.Event()
            race_window_closed = process_context.Event()
            active_guard = process_context.Lock()
            active = process_context.Value("i", 0)
            overlap = process_context.Event()

            def coordinated_rmtree(path, *args, **kwargs):
                if Path(path) != lock_path or race_window_closed.is_set():
                    return real_rmtree(path, *args, **kwargs)
                with removal_guard:
                    removal_count.value += 1
                    removal_number = removal_count.value
                if removal_number == 1:
                    if not second_reclaimer_ready.wait(timeout=0.5):
                        race_window_closed.set()
                        return real_rmtree(path, *args, **kwargs)
                    result = real_rmtree(path, *args, **kwargs)
                    stale_lock_removed.set()
                    return result
                if removal_number == 2:
                    second_reclaimer_ready.set()
                    if not stale_lock_removed.wait(timeout=5):
                        raise TimeoutError("first reclaimer did not remove the stale lock")
                    if not first_critical_section.wait(timeout=5):
                        raise TimeoutError("first contender did not acquire the replacement lock")
                    race_window_closed.set()
                    return real_rmtree(path, *args, **kwargs)
                return real_rmtree(path, *args, **kwargs)

            def coordinated_write(path: Path, text: str) -> None:
                with active_guard:
                    is_first = not first_critical_section.is_set()
                    if active.value:
                        overlap.set()
                        release_first.set()
                    active.value += 1
                    first_critical_section.set()
                try:
                    if is_first:
                        release_first.wait(timeout=1)
                    atomic_write_text(path, text)
                finally:
                    with active_guard:
                        active.value -= 1

            def contender(store: ArtifactStore, relative: str) -> None:
                store.write_text(relative, f"{relative}\n")

            processes = [
                process_context.Process(target=contender, args=(first, "first.txt")),
                process_context.Process(target=contender, args=(second, "second.txt")),
            ]
            with (
                mock.patch("manageroo.artifacts.shutil.rmtree", side_effect=coordinated_rmtree),
                mock.patch(
                    "manageroo.artifacts.atomic_write_text",
                    side_effect=coordinated_write,
                ),
            ):
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(timeout=10)

            self.assertTrue(all(not process.is_alive() for process in processes))
            self.assertEqual([process.exitcode for process in processes], [0, 0])
            self.assertFalse(overlap.is_set())
            ledger = json.loads((root / "artifact-ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(set(ledger["artifacts"]), {"first.txt", "second.txt"})

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
