import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from manageroo.discovery_preflight import (
    _descriptor_scan_supported,
    _repo_text,
    _signal_present,
    build_discovery_preflight,
)


DESCRIPTOR_SCAN_AVAILABLE = _descriptor_scan_supported()


class DiscoveryPreflightTests(unittest.TestCase):
    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_signals_treat_underscores_as_term_boundaries(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "signals.py").write_text(
                "auth_required = True\npayment_processor = None\ndeploy_config = {}\n",
                encoding="utf-8",
            )
            preflight = build_discovery_preflight(repo, "Update internal settings.", {"notes": []})

        categories = {item["category"] for item in preflight["repo_signals"]}
        self.assertIn("identity-and-access", categories)
        self.assertIn("money-and-billing", categories)
        self.assertIn("deployment-and-runtime", categories)
        self.assertFalse(_signal_present("reauthorize", "auth"))

    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_signals_surface_relevant_unknown_unknown_categories(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "package.json").write_text(
                '{"dependencies":{"next":"latest","stripe":"latest"}}',
                encoding="utf-8",
            )
            (repo / "schema.sql").write_text("create table users(id integer);", encoding="utf-8")
            capacity = {
                "manageroo_core": {
                    "hardware_agnostic": True,
                    "auto_tunes_worker_concurrency_from_hardware": False,
                },
                "notes": [],
            }
            preflight = build_discovery_preflight(
                repo,
                "Add login and checkout without breaking production deployment.",
                capacity,
            )
        categories = {item["category"] for item in preflight["repo_signals"]}
        self.assertIn("identity-and-access", categories)
        self.assertIn("money-and-billing", categories)
        self.assertIn("data-and-migrations", categories)
        self.assertIn("deployment-and-runtime", categories)
        self.assertIn("user-facing-quality", categories)
        self.assertIn("does not automatically change Manageroo worker concurrency", preflight["capacity_notes"][0])

    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_prunes_skipped_directories_before_descent(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            src = repo / "src"
            src.mkdir()
            (src / "app.py").write_text("login = True\n", encoding="utf-8")
            ignored = repo / "node_modules"
            ignored.mkdir()
            (ignored / "ignored.txt").write_text("ignored-marker\n", encoding="utf-8")
            corpus = _repo_text(repo, max_files=10)
            self.assertIn("login = true", corpus)
            self.assertNotIn("ignored-marker", corpus)

    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_stops_at_file_cap(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for index in range(5):
                (repo / f"file-{index}.txt").write_text(f"marker-{index}\n", encoding="utf-8")
            corpus = _repo_text(repo, max_files=2, max_chars=100_000)
            markers = [f"marker-{index}" for index in range(5) if f"marker-{index}" in corpus]
            self.assertEqual(len(markers), 2)

    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_stops_at_entry_cap_without_exhausting_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            names = [f"ignored-{index}.bin" for index in range(5)] + ["marker.txt"]
            for name in names:
                (repo / name).write_text("marker\n", encoding="utf-8")
            visited: list[str] = []

            class Entry:
                def __init__(self, name: str):
                    self.name = name

                def stat(self, *, follow_symlinks: bool = True):
                    visited.append(self.name)
                    return os.stat(repo / self.name, follow_symlinks=follow_symlinks)

            def scan_directory(_descriptor):
                return (Entry(name) for name in names)

            with patch("manageroo.discovery_preflight.os.scandir", side_effect=scan_directory):
                corpus = _repo_text(
                    repo,
                    max_files=10,
                    max_chars=100_000,
                    max_entries=3,
                )

            self.assertEqual(visited, names[:3])
            self.assertNotIn("marker.txt", corpus)

    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_stops_at_directory_cap(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            for index in range(5):
                directory = repo / f"directory-{index}"
                directory.mkdir()
                (directory / "marker.txt").write_text(
                    f"marker-{index}\n",
                    encoding="utf-8",
                )

            corpus = _repo_text(
                repo,
                max_files=10,
                max_chars=100_000,
                max_entries=100,
                max_directories=2,
            )

            markers = [f"marker-{index}" for index in range(5) if f"marker-{index}" in corpus]
            self.assertEqual(markers, ["marker-0"])

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs are not available on this platform")
    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_skips_fifo_without_opening_it(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            fifo = repo / "payload.txt"
            os.mkfifo(fifo)
            (repo / "safe.txt").write_text("safe-marker\n", encoding="utf-8")
            corpus = _repo_text(repo, max_files=10, max_chars=100_000)
            self.assertIn("safe-marker", corpus)
            self.assertNotIn("payload.txt", corpus)

    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_rejects_file_replaced_by_external_symlink_before_open(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            repo.mkdir()
            candidate = repo / "payload.txt"
            candidate.write_text("inside-marker\n", encoding="utf-8")
            outside = root / "outside.txt"
            outside.write_text("outside-secret-marker\n", encoding="utf-8")
            real_open = os.open
            swapped = False

            def swap_then_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == candidate.name and kwargs.get("dir_fd") is not None and not swapped:
                    candidate.unlink()
                    candidate.symlink_to(outside)
                    swapped = True
                return real_open(path, flags, *args, **kwargs)

            try:
                with patch("manageroo.discovery_preflight.os.open", side_effect=swap_then_open):
                    corpus = _repo_text(repo, max_files=10, max_chars=100_000)
            except OSError as exc:
                self.skipTest(f"file symlinks unavailable: {exc}")

            self.assertTrue(swapped)
            self.assertNotIn("outside-secret-marker", corpus)
            self.assertNotIn("payload.txt", corpus)

    @unittest.skipUnless(
        hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
        "nonblocking FIFOs are not available on this platform",
    )
    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_does_not_block_when_file_becomes_fifo_before_open(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            candidate = repo / "payload.txt"
            candidate.write_text("inside-marker\n", encoding="utf-8")
            real_open = os.open
            swapped = False

            def swap_then_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == candidate.name and kwargs.get("dir_fd") is not None and not swapped:
                    candidate.unlink()
                    os.mkfifo(candidate)
                    swapped = True
                    self.assertTrue(flags & os.O_NONBLOCK)
                return real_open(path, flags, *args, **kwargs)

            with patch("manageroo.discovery_preflight.os.open", side_effect=swap_then_open):
                corpus = _repo_text(repo, max_files=10, max_chars=100_000)

            self.assertTrue(swapped)
            self.assertNotIn("payload.txt", corpus)

    @unittest.skipUnless(DESCRIPTOR_SCAN_AVAILABLE, "descriptor-relative scans are unavailable")
    def test_repo_text_keeps_scanned_parent_pinned_when_path_becomes_external_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = root / "repo"
            scanned = repo / "scanned"
            outside = root / "outside"
            scanned.mkdir(parents=True)
            outside.mkdir()
            candidate = scanned / "payload.txt"
            candidate.write_text("inside-marker\n", encoding="utf-8")
            (outside / candidate.name).write_text("outside-secret-marker\n", encoding="utf-8")
            parked = root / "parked-scanned"
            real_open = os.open
            swapped = False

            def swap_parent_then_open(path, flags, *args, **kwargs):
                nonlocal swapped
                if path == candidate.name and kwargs.get("dir_fd") is not None and not swapped:
                    scanned.rename(parked)
                    scanned.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return real_open(path, flags, *args, **kwargs)

            try:
                with patch(
                    "manageroo.discovery_preflight.os.open",
                    side_effect=swap_parent_then_open,
                ):
                    corpus = _repo_text(repo, max_files=10, max_chars=100_000)
            except OSError as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")

            self.assertTrue(swapped)
            self.assertIn("inside-marker", corpus)
            self.assertNotIn("outside-secret-marker", corpus)
            self.assertIn("scanned/payload.txt", corpus)

    def test_repo_text_fails_closed_without_descriptor_relative_primitives(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp)
            (repo / "payload.txt").write_text("secret-marker\n", encoding="utf-8")
            with patch(
                "manageroo.discovery_preflight._descriptor_scan_supported",
                return_value=False,
            ):
                corpus = _repo_text(repo, max_files=10, max_chars=100_000)

            self.assertEqual(corpus, "")

    def test_preflight_always_reviews_recovery_observability_proof_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            preflight = build_discovery_preflight(
                Path(temp),
                "Change one internal function.",
                {
                    "manageroo_core": {
                        "hardware_agnostic": True,
                        "auto_tunes_worker_concurrency_from_hardware": False,
                    },
                    "notes": [],
                },
            )
        categories = {item["category"] for item in preflight["always_review"]}
        self.assertEqual(
            categories,
            {
                "failure-and-recovery",
                "observability-and-support",
                "verification-strength",
                "scope-and-non-goals",
            },
        )
        self.assertIn("ask_only_when", preflight["decision_policy"])
        self.assertIn("do_not_block_for", preflight["decision_policy"])
        self.assertTrue(
            any(
                "Manageroo host having different CPU" in item
                for item in preflight["decision_policy"]["do_not_block_for"]
            )
        )


if __name__ == "__main__":
    unittest.main()
