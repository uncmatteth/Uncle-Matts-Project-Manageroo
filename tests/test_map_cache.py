import tempfile
import unittest
from pathlib import Path

from manageroo.map_cache import (
    inventory_fingerprint,
    load_system_map_cache,
    write_system_map_cache,
)


class MapCacheTests(unittest.TestCase):
    def test_loads_only_exact_inventory_and_brief_match(self):
        inventory = [
            {"path": "a.py", "sha256": "aaa", "bytes": 10},
            {"path": "b.py", "sha256": "bbb", "bytes": 20},
        ]
        system_map = {"status": "mapped", "modules": []}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "system-map-cache.json"
            write_system_map_cache(
                path,
                inventory=inventory,
                brief="Build X",
                system_map=system_map,
            )
            self.assertEqual(
                load_system_map_cache(path, inventory=inventory, brief="Build X"),
                system_map,
            )
            self.assertIsNone(load_system_map_cache(path, inventory=inventory, brief="Build Y"))
            changed = [*inventory, {"path": "c.py", "sha256": "ccc", "bytes": 30}]
            self.assertIsNone(load_system_map_cache(path, inventory=changed, brief="Build X"))

    def test_inventory_fingerprint_is_order_stable(self):
        left = [
            {"path": "b.py", "sha256": "bbb", "bytes": 20},
            {"path": "a.py", "sha256": "aaa", "bytes": 10},
        ]
        right = list(reversed(left))
        self.assertEqual(inventory_fingerprint(left), inventory_fingerprint(right))


if __name__ == "__main__":
    unittest.main()
