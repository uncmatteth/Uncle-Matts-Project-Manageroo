import json
import multiprocessing
import os
import shutil
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from manageroo.artifacts import ArtifactStore
from manageroo.errors import SafetyError
from manageroo.util import atomic_write_text


def _hold_artifact_lock_with_delayed_owner(
    root: str,
    owner_write_started,
    resume_owner_write,
    first_entered,
    release_first,
) -> None:
    store = ArtifactStore(Path(root))
    real_write_owner = ArtifactStore._write_owner_at

    def delayed_owner_write(active_store, directory_fd: int, token: str):
        if not owner_write_started.is_set():
            owner_write_started.set()
            if not resume_owner_write.wait(timeout=15):
                raise TimeoutError("test did not resume first owner publication")
        return real_write_owner(active_store, directory_fd, token)

    with mock.patch.object(ArtifactStore, "_write_owner_at", new=delayed_owner_write):
        with store._transaction_lock():
            first_entered.set()
            if not release_first.wait(timeout=15):
                raise TimeoutError("test did not release first transaction lock")


def _acquire_artifact_lock_after_owner(
    root: str,
    lock_path: str,
    initialized,
    start_attempt,
    reclaimer_ready,
    resume_reclaimer,
    second_entered,
) -> None:
    real_rename = os.rename
    store = ArtifactStore(Path(root))
    initialized.set()
    if not start_attempt.wait(timeout=15):
        raise TimeoutError("test did not start second lock attempt")

    def delayed_reclaim_rename(source, destination, *args, **kwargs):
        if Path(source) == Path(lock_path) and ".reclaimed-" in Path(destination).name:
            reclaimer_ready.set()
            if not resume_reclaimer.wait(timeout=15):
                raise TimeoutError("test did not resume abandoned-lock rename")
        return real_rename(source, destination, *args, **kwargs)

    with mock.patch("manageroo.artifacts.os.rename", side_effect=delayed_reclaim_rename):
        with store._transaction_lock():
            second_entered.set()


class ArtifactConcurrencyTests(unittest.TestCase):
    def test_delayed_owner_publication_cannot_be_reclaimed_while_writer_is_active(self):
        process_context = multiprocessing.get_context("spawn")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "artifacts"
            lock_path = root / ".artifact-ledger.lock"
            owner_write_started = process_context.Event()
            resume_owner_write = process_context.Event()
            reclaimer_ready = process_context.Event()
            resume_reclaimer = process_context.Event()
            second_initialized = process_context.Event()
            start_second = process_context.Event()
            first_entered = process_context.Event()
            release_first = process_context.Event()
            second_entered = process_context.Event()

            first_process = process_context.Process(
                target=_hold_artifact_lock_with_delayed_owner,
                args=(
                    str(root),
                    owner_write_started,
                    resume_owner_write,
                    first_entered,
                    release_first,
                ),
            )
            second_process = process_context.Process(
                target=_acquire_artifact_lock_after_owner,
                args=(
                    str(root),
                    str(lock_path),
                    second_initialized,
                    start_second,
                    reclaimer_ready,
                    resume_reclaimer,
                    second_entered,
                ),
            )
            try:
                second_process.start()
                self.assertTrue(second_initialized.wait(timeout=15))
                first_process.start()
                self.assertTrue(owner_write_started.wait(timeout=15))
                stale_time = time.time() - 10
                os.utime(lock_path, (stale_time, stale_time))
                start_second.set()

                # Vulnerable implementations reach the final rename after deciding
                # the still-unpublished owner is abandoned. A real advisory lock keeps
                # the contender outside directory reclamation entirely.
                reclaimer_ready.wait(timeout=0.5)
                resume_owner_write.set()
                self.assertTrue(first_entered.wait(timeout=15))
                resume_reclaimer.set()
                self.assertFalse(second_entered.wait(timeout=0.2))

                release_first.set()
                self.assertTrue(second_entered.wait(timeout=15))
                first_process.join(timeout=15)
                second_process.join(timeout=15)
                self.assertEqual(first_process.exitcode, 0)
                self.assertEqual(second_process.exitcode, 0)
            finally:
                resume_owner_write.set()
                resume_reclaimer.set()
                start_second.set()
                release_first.set()
                for process in (first_process, second_process):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

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

            real_reclaim = ArtifactStore._reclaim_abandoned_lock
            reclaimer_guard = process_context.Lock()
            reclaimer_count = process_context.Value("i", 0)
            reclaimers_ready = process_context.Event()
            release_reclaimers = process_context.Event()
            first_critical_section = process_context.Event()
            release_first = process_context.Event()
            active_guard = process_context.Lock()
            active = process_context.Value("i", 0)
            overlap = process_context.Event()

            @contextmanager
            def bypass_advisory_lock(store, *, timeout_seconds):
                yield

            def coordinated_reclaim(store):
                coordinated = False
                with reclaimer_guard:
                    if not reclaimers_ready.is_set():
                        reclaimer_count.value += 1
                        coordinated = True
                        if reclaimer_count.value == 2:
                            reclaimers_ready.set()
                if coordinated and not release_reclaimers.wait(timeout=5):
                    raise TimeoutError("test did not release competing reclaimers")
                return real_reclaim(store)

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
            try:
                with (
                    mock.patch.object(
                        ArtifactStore,
                        "_advisory_transaction_lock",
                        new=bypass_advisory_lock,
                    ),
                    mock.patch.object(
                        ArtifactStore,
                        "_reclaim_abandoned_lock",
                        new=coordinated_reclaim,
                    ),
                    mock.patch(
                        "manageroo.artifacts.atomic_write_text",
                        side_effect=coordinated_write,
                    ),
                ):
                    for process in processes:
                        process.start()
                    self.assertTrue(reclaimers_ready.wait(timeout=5))
                    self.assertEqual(reclaimer_count.value, 2)
                    release_reclaimers.set()
                    self.assertTrue(first_critical_section.wait(timeout=5))
                    self.assertFalse(overlap.wait(timeout=0.2))
                    release_first.set()
                    for process in processes:
                        process.join(timeout=10)

                self.assertTrue(all(not process.is_alive() for process in processes))
                self.assertEqual([process.exitcode for process in processes], [0, 0])
                self.assertEqual(reclaimer_count.value, 2)
                self.assertFalse(overlap.is_set())
                ledger = json.loads((root / "artifact-ledger.json").read_text(encoding="utf-8"))
                self.assertEqual(set(ledger["artifacts"]), {"first.txt", "second.txt"})
            finally:
                release_reclaimers.set()
                release_first.set()
                for process in processes:
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)

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
