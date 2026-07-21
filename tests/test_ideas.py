import tempfile
import threading
import unittest
from pathlib import Path

from manageroo.ideas import IdeaInbox


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


if __name__ == "__main__":
    unittest.main()
