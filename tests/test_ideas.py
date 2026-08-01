import multiprocessing
import tempfile
import threading
import unittest
from pathlib import Path

from manageroo.ideas import IdeaInbox


def _hold_idea_lock_before_owner_publication(repo, publication_paused, release, results) -> None:
    import manageroo.ideas as ideas

    original_write = ideas.os.write

    def delayed_write(descriptor, data):
        publication_paused.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release owner publication")
        return original_write(descriptor, data)

    ideas.os.write = delayed_write
    results.put(("owner", IdeaInbox(Path(repo)).attach_pending("owner")))


def _attach_after_lock_open(repo, lock_opened, completed, results) -> None:
    import manageroo.ideas as ideas

    original_open = ideas.os.open

    def observed_open(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        lock_opened.set()
        return descriptor

    ideas.os.open = observed_open
    results.put(("contender", IdeaInbox(Path(repo)).attach_pending("contender")))
    completed.set()


class IdeaTests(unittest.TestCase):
    def test_capture_and_attach(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            inbox = IdeaInbox(repo)
            inbox.add("Add approvals later", "future-feature")
            self.assertEqual(len(inbox.list("captured")), 1)
            attached = inbox.attach_pending("run-1")
            self.assertEqual(attached[0]["linked_run"], "run-1")
            self.assertEqual(len(inbox.list("attached")), 1)

    def test_concurrent_attach_claims_each_idea_for_exactly_one_run(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            IdeaInbox(repo).add("Only one run may own me", "future-feature")
            barrier = threading.Barrier(3)
            results: dict[str, list[dict]] = {}
            errors: list[BaseException] = []

            def claim(run_id: str) -> None:
                try:
                    inbox = IdeaInbox(repo)
                    barrier.wait(timeout=5)
                    results[run_id] = inbox.attach_pending(run_id)
                except BaseException as exc:
                    errors.append(exc)

            threads = [
                threading.Thread(target=claim, args=("run-a",)),
                threading.Thread(target=claim, args=("run-b",)),
            ]
            for thread in threads:
                thread.start()
            barrier.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=10)

            self.assertEqual(errors, [])
            claimed = [(run_id, items) for run_id, items in results.items() if items]
            self.assertEqual(len(claimed), 1)
            winner, items = claimed[0]
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["linked_run"], winner)
            persisted = IdeaInbox(repo).list("attached")
            self.assertEqual(len(persisted), 1)
            self.assertEqual(persisted[0]["linked_run"], winner)

    def test_contender_waits_while_lock_owner_metadata_is_unpublished(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            IdeaInbox(repo).add("The initialized owner keeps its lock", "future-feature")
            context = multiprocessing.get_context("spawn")
            publication_paused = context.Event()
            release = context.Event()
            contender_opened = context.Event()
            contender_completed = context.Event()
            results = context.Queue()
            owner = context.Process(
                target=_hold_idea_lock_before_owner_publication,
                args=(repo, publication_paused, release, results),
            )
            contender = context.Process(
                target=_attach_after_lock_open,
                args=(repo, contender_opened, contender_completed, results),
            )

            try:
                owner.start()
                self.assertTrue(publication_paused.wait(timeout=5))
                contender.start()
                self.assertTrue(contender_opened.wait(timeout=5))
                self.assertFalse(contender_completed.wait(timeout=0.3))
                release.set()
                owner.join(timeout=5)
                contender.join(timeout=5)
                self.assertEqual(owner.exitcode, 0)
                self.assertEqual(contender.exitcode, 0)
                claims = dict(results.get(timeout=2) for _ in range(2))
                self.assertEqual(len(claims["owner"]), 1)
                self.assertEqual(claims["contender"], [])
                self.assertEqual(IdeaInbox(repo).list("attached")[0]["linked_run"], "owner")
            finally:
                release.set()
                for process in (owner, contender):
                    if process.pid is not None:
                        process.join(timeout=1)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=1)
                results.close()


if __name__ == "__main__":
    unittest.main()
