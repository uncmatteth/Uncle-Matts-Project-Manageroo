import importlib.util
import io
import json
import os
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
            descendant = (
                "import signal, time; from pathlib import Path; "
                "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                f"Path({str(pid_file)!r}).write_text(str(__import__('os').getpid()), encoding='utf-8'); "
                f"time.sleep(1); Path({str(marker)!r}).write_text('survived', encoding='utf-8'); "
                "time.sleep(10)"
            )
            parent = (
                "import subprocess, sys, time; "
                f"subprocess.Popen([sys.executable, '-c', {descendant!r}], "
                "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                "time.sleep(10)"
            )
            with patch.object(release, "PROCESS_TREE_GRACE_SECONDS", 0.1):
                result = release.run([sys.executable, "-c", parent], timeout=0.2)

            self.assertEqual(result["exit_code"], 124)
            self.assertIn("TIMEOUT", result["output"])
            self.assertTrue(pid_file.is_file())
            descendant_pid = int(pid_file.read_text(encoding="utf-8"))
            time.sleep(1)
            self.assertFalse(marker.exists())
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                descendant_running = False
            else:
                descendant_running = True
                if Path("/proc").is_dir():
                    try:
                        state = Path(f"/proc/{descendant_pid}/stat").read_text(
                            encoding="utf-8", errors="replace"
                        ).split()[2]
                    except FileNotFoundError:
                        descendant_running = False
                    else:
                        descendant_running = state != "Z"
            self.assertFalse(descendant_running)

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
