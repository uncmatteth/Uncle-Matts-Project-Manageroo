from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from manageroo.clawpatch_batch import batch_fix_open_findings, open_finding_ids
from manageroo.errors import SafetyError


class ClawpatchBatchTests(unittest.TestCase):
    def test_report_derived_finding_queue_is_disabled(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for operation in (open_finding_ids, batch_fix_open_findings):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(SafetyError, "disabled"):
                        operation(repo)


if __name__ == "__main__":
    unittest.main()
