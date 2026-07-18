import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.system_capacity import format_capacity, host_capacity


class SystemCapacityTests(unittest.TestCase):
    def test_capacity_profile_contains_controller_recommendations(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("manageroo.system_capacity._total_memory_bytes", return_value=64 * 1024**3):
                with patch(
                    "manageroo.system_capacity._nvidia_gpus",
                    return_value=[{"name": "Test GPU", "vram_mib": 16384, "vram_gib": 16.0}],
                ):
                    with patch("manageroo.system_capacity.os.cpu_count", return_value=16):
                        profile = host_capacity(Path(temp))
        self.assertEqual(profile["memory"]["total_gib"], 64.0)
        self.assertEqual(profile["gpu"]["max_vram_gib"], 16.0)
        self.assertEqual(profile["recommendations"]["capacity_class"], "high-capacity-local")
        self.assertEqual(profile["recommendations"]["max_parallel_agent_calls"], 8)

    def test_capacity_output_is_plain_english(self):
        profile = {
            "platform": {"system": "Linux", "release": "test", "machine": "x86_64"},
            "cpu": {"logical_cores": 8},
            "memory": {"total_gib": 32.0},
            "gpu": {"devices": [], "max_vram_gib": None},
            "disk": {"free_gib": 100.0},
            "recommendations": {
                "capacity_class": "strong-general-purpose",
                "max_parallel_agent_calls": 4,
            },
            "warnings": [],
        }
        text = format_capacity(profile)
        self.assertIn("SYSTEM CAPACITY", text)
        self.assertIn("RAM: 32.0 GiB", text)
        self.assertIn("Recommended max parallel agent calls: 4", text)


if __name__ == "__main__":
    unittest.main()
