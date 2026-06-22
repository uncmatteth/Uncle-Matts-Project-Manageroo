import tempfile
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


if __name__ == "__main__":
    unittest.main()
