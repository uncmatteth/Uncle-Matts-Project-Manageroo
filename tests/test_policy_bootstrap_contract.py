from __future__ import annotations

import unittest

import manageroo
from manageroo.orchestrator import Orchestrator


class PolicyBootstrapContractTests(unittest.TestCase):
    def test_package_import_installs_external_repair_lane(self):
        self.assertTrue(manageroo.__version__)
        self.assertTrue(
            getattr(Orchestrator, "_manageroo_external_repair_policy_installed", False)
        )
        self.assertTrue(callable(getattr(Orchestrator, "_run_external_review_repair_lanes", None)))


if __name__ == "__main__":
    unittest.main()
