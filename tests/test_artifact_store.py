import json
import tempfile
import threading
import unittest
from pathlib import Path

from manageroo.artifacts import ArtifactStore
from manageroo.errors import SafetyError


class ArtifactStoreTests(unittest.TestCase):
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
