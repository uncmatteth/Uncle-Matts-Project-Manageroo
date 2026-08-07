import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("manageroo_release_driver", ROOT / "scripts" / "release.py")
assert SPEC and SPEC.loader
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


class ReleaseDriverTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX process-group assertion")
    def test_timeout_force_kills_sigterm_resistant_redirected_descendant(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / "descendant-survived.txt"
            pid_file = root / "descendant.pid"
            ready_file = root / "descendant.ready"
            descendant = (
                "import signal, time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"Path({str(ready_file)!r}).write_text('ready', encoding='utf-8'); "
                f"time.sleep(2); Path({str(marker)!r}).write_text('survived', encoding='utf-8'); "
                "time.sleep(10)"
            )
            parent = (
                "import subprocess, sys, time; from pathlib import Path; "
                f"child = subprocess.Popen([sys.executable, '-c', {descendant!r}], "
                "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                f"Path({str(pid_file)!r}).write_text(str(child.pid), encoding='utf-8'); "
                "time.sleep(10)"
            )
            launched_process = None
            descendant_pid = None
            real_popen = subprocess.Popen

            def process_is_running(pid):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    return False
                proc_stat = Path(f"/proc/{pid}/stat")
                if proc_stat.is_file():
                    try:
                        state = proc_stat.read_text(
                            encoding="utf-8", errors="replace"
                        ).split()[2]
                    except FileNotFoundError:
                        return False
                    return state != "Z"
                status = subprocess.run(
                    ["ps", "-o", "stat=", "-p", str(pid)],
                    check=False,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                )
                return status.returncode == 0 and not status.stdout.lstrip().startswith("Z")

            def popen_after_descendant_ready(*args, **kwargs):
                nonlocal launched_process
                launched_process = real_popen(*args, **kwargs)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if pid_file.is_file() and ready_file.is_file():
                        break
                    time.sleep(0.01)
                return launched_process

            try:
                with patch.object(
                    release.subprocess, "Popen", side_effect=popen_after_descendant_ready
                ), patch.object(release, "PROCESS_TREE_GRACE_SECONDS", 0.1):
                    result = release.run([sys.executable, "-c", parent], timeout=0.5)

                self.assertEqual(result["exit_code"], 124)
                self.assertIn("TIMEOUT", result["output"])
                self.assertTrue(pid_file.is_file())
                self.assertTrue(ready_file.is_file())
                descendant_pid = int(pid_file.read_text(encoding="utf-8"))
                deadline = time.monotonic() + 3
                while process_is_running(descendant_pid) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(marker.exists())
                self.assertFalse(process_is_running(descendant_pid))
            finally:
                if launched_process is not None and launched_process.poll() is None:
                    try:
                        os.killpg(launched_process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        launched_process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                if descendant_pid is None and pid_file.is_file():
                    try:
                        descendant_pid = int(pid_file.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        pass
                if descendant_pid is not None and process_is_running(descendant_pid):
                    try:
                        os.kill(descendant_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_failed_product_proof_never_runs_packaging(self):
        proof = {
            "argv": [sys.executable, "-m", "manageroo", "prove", "--json"],
            "exit_code": 2,
            "output": json.dumps({"ok": False, "status": "PARTIAL"}),
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["release.py", "--json"]), patch.object(
            release, "run", return_value=proof
        ) as run, redirect_stdout(output):
            code = release.main()
        self.assertEqual(code, 2)
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    [sys.executable, "-m", "manageroo", "prove", "--json"],
                    timeout=release.PRODUCT_PROOF_TIMEOUT_SECONDS,
                )
            ],
        )
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["release_created"])
        self.assertEqual(payload["stage"], "product-proof")

    def test_complete_product_proof_runs_exact_package_pipeline_after_proof(self):
        proof = {
            "argv": [sys.executable, "-m", "manageroo", "prove", "--json"],
            "exit_code": 0,
            "output": json.dumps({"ok": True, "status": "COMPLETE"}),
        }
        package = {
            "argv": [sys.executable, "scripts/package_release.py"],
            "exit_code": 0,
            "output": "release paths\n",
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["release.py", "--json"]), patch.object(
            release, "run", side_effect=[proof, package]
        ) as run, redirect_stdout(output):
            code = release.main()
        self.assertEqual(code, 0)
        self.assertEqual(
            run.call_args_list,
            [
                call(
                    [sys.executable, "-m", "manageroo", "prove", "--json"],
                    timeout=release.PRODUCT_PROOF_TIMEOUT_SECONDS,
                ),
                call(
                    [sys.executable, "scripts/package_release.py"],
                    timeout=release.PACKAGE_TIMEOUT_SECONDS,
                ),
            ],
        )
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["release_created"])
        self.assertEqual(payload["stage"], "complete")

    def test_packaging_failure_never_claims_release_created(self):
        proof = {
            "argv": [sys.executable, "-m", "manageroo", "prove", "--json"],
            "exit_code": 0,
            "output": json.dumps({"ok": True, "status": "COMPLETE"}),
        }
        package = {
            "argv": [sys.executable, "scripts/package_release.py"],
            "exit_code": 1,
            "output": "packaging failed\n",
        }
        output = io.StringIO()
        with patch.object(sys, "argv", ["release.py", "--json"]), patch.object(
            release, "run", side_effect=[proof, package]
        ), redirect_stdout(output):
            code = release.main()
        self.assertEqual(code, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["release_created"])
        self.assertEqual(payload["stage"], "packaging")
        self.assertEqual(payload["package"]["exit_code"], 1)

    def test_live_agent_is_forwarded_only_to_product_proof(self):
        proof = {
            "argv": [],
            "exit_code": 0,
            "output": json.dumps({"ok": True, "status": "COMPLETE"}),
        }
        package = {"argv": [], "exit_code": 0, "output": "ok\n"}
        with patch.object(
            sys, "argv", ["release.py", "--json", "--live-agent", "codex"]
        ), patch.object(release, "run", side_effect=[proof, package]) as run, redirect_stdout(io.StringIO()):
            code = release.main()
        self.assertEqual(code, 0)
        self.assertEqual(
            run.call_args_list[0],
            call(
                [
                    sys.executable,
                    "-m",
                    "manageroo",
                    "prove",
                    "--json",
                    "--live-agent",
                    "codex",
                ],
                timeout=release.PRODUCT_PROOF_TIMEOUT_SECONDS,
            ),
        )
        self.assertEqual(
            run.call_args_list[1],
            call(
                [sys.executable, "scripts/package_release.py"],
                timeout=release.PACKAGE_TIMEOUT_SECONDS,
            ),
        )


if __name__ == "__main__":
    unittest.main()
