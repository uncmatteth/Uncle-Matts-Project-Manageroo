from __future__ import annotations

import importlib.util
import multiprocessing
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from manageroo.assets import asset_path


def _load_gate():
    gate_path = asset_path("supervisor_gate/manageroo_supervisor_gate.py")
    spec = importlib.util.spec_from_file_location("test_supervisor_gate_asset", gate_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load supervisor runtime gate")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return gate


def _hold_runtime_lock(executable: str, acquired, release) -> None:
    gate = _load_gate()
    sys.argv = [executable, "--repo", "."]
    with gate._runtime_lock():
        acquired.set()
        if not release.wait(timeout=5):
            raise TimeoutError("test did not release runtime lock")


class _OsProxy:
    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, name: str):
        return getattr(os, name)


class SupervisorGateTests(unittest.TestCase):
    def _executable(self, root: Path) -> Path:
        executable = root / "bin" / "clawpatch-supervise"
        executable.parent.mkdir()
        executable.write_text("", encoding="utf-8")
        return executable

    def test_posix_lock_acquires_releases_and_closes_after_body_exception(self):
        gate = _load_gate()
        fake_fcntl = SimpleNamespace(
            LOCK_EX=1,
            LOCK_NB=2,
            LOCK_UN=4,
            flock=Mock(),
        )
        original_close = os.close
        closed_descriptors: list[int] = []

        def close_descriptor(descriptor: int) -> None:
            closed_descriptors.append(descriptor)
            original_close(descriptor)

        with tempfile.TemporaryDirectory() as temp:
            executable = self._executable(Path(temp))
            with (
                patch.object(gate.sys, "argv", [str(executable)]),
                patch.object(gate, "os", _OsProxy("posix")),
                patch.dict(sys.modules, {"fcntl": fake_fcntl}),
                patch.object(gate.os, "close", side_effect=close_descriptor),
            ):
                with self.assertRaisesRegex(RuntimeError, "body failed"):
                    with gate._runtime_lock():
                        raise RuntimeError("body failed")

        descriptor = closed_descriptors[0]
        fake_fcntl.flock.assert_has_calls(
            [
                call(descriptor, fake_fcntl.LOCK_EX | fake_fcntl.LOCK_NB),
                call(descriptor, fake_fcntl.LOCK_UN),
            ]
        )
        with self.assertRaises(OSError):
            os.fstat(descriptor)

    def test_windows_lock_uses_nonblocking_byte_range_and_unlocks(self):
        gate = _load_gate()
        fake_msvcrt = SimpleNamespace(
            LK_NBLCK=1,
            LK_UNLCK=2,
            locking=Mock(),
        )
        with tempfile.TemporaryDirectory() as temp:
            executable = self._executable(Path(temp))
            with (
                patch.object(gate.sys, "argv", [str(executable)]),
                patch.object(gate, "os", _OsProxy("nt")),
                patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
            ):
                with gate._runtime_lock():
                    pass

        descriptor = fake_msvcrt.locking.call_args_list[0].args[0]
        fake_msvcrt.locking.assert_has_calls(
            [
                call(descriptor, fake_msvcrt.LK_NBLCK, 1),
                call(descriptor, fake_msvcrt.LK_UNLCK, 1),
            ]
        )

    def test_contention_returns_75_then_allows_acquisition_after_release(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = self._executable(Path(temp))
            acquired = multiprocessing.Event()
            release = multiprocessing.Event()
            holder = multiprocessing.Process(
                target=_hold_runtime_lock,
                args=(str(executable), acquired, release),
            )
            holder.start()
            try:
                self.assertTrue(acquired.wait(timeout=5))
                gate = _load_gate()
                run_supervisor = Mock(return_value=0)
                stderr = StringIO()
                with (
                    patch.object(gate.sys, "argv", [str(executable), "--repo", "."]),
                    patch.object(gate, "_run_supervisor", run_supervisor),
                    redirect_stderr(stderr),
                ):
                    self.assertEqual(gate.main(), gate.TRANSIENT_EXIT_CODE)
                run_supervisor.assert_not_called()
                self.assertEqual(
                    stderr.getvalue(),
                    "The ClawPatch supervisor installation is being updated or is already active.\n",
                )
            finally:
                release.set()
                holder.join(timeout=5)
                if holder.is_alive():
                    holder.terminate()
                    holder.join(timeout=5)

            self.assertEqual(holder.exitcode, 0)
            gate = _load_gate()
            with (
                patch.object(gate.sys, "argv", [str(executable), "--repo", "."]),
                patch.object(gate, "_run_supervisor", return_value=0) as run_supervisor,
            ):
                self.assertEqual(gate.main(), 0)
            run_supervisor.assert_called_once_with()

    def test_supervisor_version_probe_uses_runtime_lock(self):
        gate = _load_gate()
        run_supervisor = Mock(return_value=0)
        stderr = StringIO()
        with (
            patch.object(gate.sys, "argv", ["clawpatch-supervise", "--version"]),
            patch.object(gate, "_runtime_lock", side_effect=gate.RuntimeLockBusy),
            patch.object(gate, "_run_supervisor", run_supervisor),
            redirect_stderr(stderr),
        ):
            self.assertEqual(gate.main(), gate.TRANSIENT_EXIT_CODE)

        run_supervisor.assert_not_called()
        self.assertIn("being updated or is already active", stderr.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX permission rule")
    def test_group_writable_lock_directory_is_rejected(self):
        gate = _load_gate()
        with tempfile.TemporaryDirectory() as temp:
            executable = self._executable(Path(temp))
            cache = executable.parent / "cache"
            cache.mkdir(mode=0o770)
            cache.chmod(0o770)
            with patch.object(gate.sys, "argv", [str(executable)]):
                with self.assertRaisesRegex(OSError, "lock directory is unsafe"):
                    with gate._runtime_lock():
                        self.fail("unsafe directory lock was acquired")

    def test_reparse_point_lock_directory_is_rejected(self):
        gate = _load_gate()
        with tempfile.TemporaryDirectory() as temp:
            executable = self._executable(Path(temp))
            with (
                patch.object(gate.sys, "argv", [str(executable)]),
                patch.object(gate, "_is_reparse_point", return_value=True),
            ):
                with self.assertRaisesRegex(OSError, "lock directory is unsafe"):
                    with gate._runtime_lock():
                        self.fail("reparse-point lock directory was acquired")

    @unittest.skipUnless(hasattr(os, "getuid"), "ownership rule unavailable")
    def test_wrong_owner_lock_file_is_rejected(self):
        gate = _load_gate()
        getuid = Mock(side_effect=[os.getuid(), os.getuid() + 1])
        posix_os = _OsProxy("posix")
        posix_os.getuid = getuid
        with tempfile.TemporaryDirectory() as temp:
            executable = self._executable(Path(temp))
            with (
                patch.object(gate.sys, "argv", [str(executable)]),
                patch.object(gate, "os", posix_os),
            ):
                with self.assertRaisesRegex(OSError, "runtime lock is unsafe"):
                    with gate._runtime_lock():
                        self.fail("wrong-owner lock file was acquired")

        self.assertEqual(getuid.call_count, 2)

    @unittest.skipIf(os.name == "nt", "POSIX permission rule")
    def test_group_readable_lock_file_is_rejected(self):
        gate = _load_gate()
        with tempfile.TemporaryDirectory() as temp:
            executable = self._executable(Path(temp))
            cache = executable.parent / "cache"
            cache.mkdir(mode=0o700)
            lock_path = cache / f"{executable.name}.manageroo.lock"
            lock_path.write_text("x", encoding="utf-8")
            lock_path.chmod(0o640)

            with patch.object(gate.sys, "argv", [str(executable)]):
                with self.assertRaisesRegex(OSError, "runtime lock is unsafe"):
                    with gate._runtime_lock():
                        self.fail("group-readable lock file was acquired")

    def test_hard_linked_lock_file_is_rejected_and_left_unchanged(self):
        gate = _load_gate()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = self._executable(root)
            cache = executable.parent / "cache"
            cache.mkdir(mode=0o700)
            victim = root / "victim.txt"
            victim.write_text("do not change", encoding="utf-8")
            victim.chmod(0o600)
            lock_path = cache / f"{executable.name}.manageroo.lock"
            try:
                os.link(victim, lock_path)
            except OSError as exc:
                self.skipTest(f"hard links unavailable: {exc}")

            with patch.object(gate.sys, "argv", [str(executable)]):
                with self.assertRaisesRegex(OSError, "runtime lock is unsafe"):
                    with gate._runtime_lock():
                        self.fail("hard-linked lock file was acquired")

            self.assertEqual(victim.read_text(encoding="utf-8"), "do not change")
            self.assertEqual(lock_path.stat().st_nlink, 2)


if __name__ == "__main__":
    unittest.main()
