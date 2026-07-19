import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.system_capacity import format_capacity, host_capacity


class SystemCapacityTests(unittest.TestCase):
    def test_host_profile_records_hardware_without_creating_manageroo_requirements(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch(
                "manageroo.system_capacity._total_memory_bytes",
                return_value=64 * 1024**3,
            ):
                with patch(
                    "manageroo.system_capacity._nvidia_gpus",
                    return_value=[
                        {
                            "name": "Test GPU",
                            "vram_mib": 16384,
                            "vram_gib": 16.0,
                        }
                    ],
                ):
                    with patch(
                        "manageroo.system_capacity.os.cpu_count",
                        return_value=16,
                    ):
                        profile = host_capacity(Path(temp))
        self.assertEqual(profile["memory"]["total_gib"], 64.0)
        self.assertEqual(profile["gpu"]["max_vram_gib"], 16.0)
        self.assertTrue(profile["manageroo_core"]["hardware_agnostic"])
        self.assertFalse(profile["manageroo_core"]["gpu_required"])
        self.assertFalse(
            profile["manageroo_core"]["auto_tunes_worker_concurrency_from_hardware"]
        )
        self.assertNotIn("recommendations", profile)

    def test_low_spec_host_is_not_reported_as_incompatible_with_manageroo(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch(
                "manageroo.system_capacity._total_memory_bytes",
                return_value=4 * 1024**3,
            ):
                with patch("manageroo.system_capacity._nvidia_gpus", return_value=[]):
                    with patch("manageroo.system_capacity.os.cpu_count", return_value=2):
                        profile = host_capacity(Path(temp))
        self.assertTrue(profile["manageroo_core"]["hardware_agnostic"])
        self.assertFalse(profile["manageroo_core"]["ram_minimum_enforced"])
        self.assertFalse(profile["manageroo_core"]["cpu_minimum_enforced"])

    def test_capacity_output_is_plain_english(self):
        profile = {
            "platform": {"system": "Linux", "release": "test", "machine": "x86_64"},
            "cpu": {"logical_cores": 8},
            "memory": {"total_gib": 32.0},
            "gpu": {"devices": [], "max_vram_gib": None},
            "disk": {"free_gib": 100.0},
            "manageroo_core": {
                "hardware_agnostic": True,
                "gpu_required": False,
                "auto_tunes_worker_concurrency_from_hardware": False,
            },
            "notes": [],
        }
        text = format_capacity(profile)
        self.assertIn("HOST HARDWARE PROFILE", text)
        self.assertIn("RAM: 32.0 GiB", text)
        self.assertIn("Manageroo core: hardware-agnostic", text)
        self.assertIn("Automatic hardware-based worker throttling: no", text)
        self.assertNotIn("Recommended max parallel agent calls", text)


if __name__ == "__main__":
    unittest.main()
