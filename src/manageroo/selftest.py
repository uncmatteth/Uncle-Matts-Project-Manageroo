from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from .adapters.mock import MockAdapter
from .orchestrator import Orchestrator
from .project import initialize_project
from .runner import CommandRunner


def _toml_array(items: list[str]) -> str:
    return "[" + ", ".join(json.dumps(item) for item in items) + "]"


def run_self_test() -> dict:
    with tempfile.TemporaryDirectory(prefix="manageroo-self-test-") as temp:
        repo = Path(temp) / "fixture"
        repo.mkdir()
        runner = CommandRunner()
        for argv in (
            ["git", "init", "-b", "main"],
            ["git", "config", "user.name", "MANAGEROO Self Test"],
            ["git", "config", "user.email", "selftest@local.invalid"],
        ):
            result = runner.run(argv, cwd=repo, timeout_seconds=30)
            if not result.passed:
                raise RuntimeError(result.stderr)

        (repo / "README.md").write_text("# Fixture\n", encoding="utf-8")
        (repo / "test_fixture.py").write_text(
            "import unittest\n"
            "from pathlib import Path\n\n"
            "class FixtureTest(unittest.TestCase):\n"
            "    def test_output(self):\n"
            "        self.assertEqual(Path('manageroo_fixture.txt').read_text(), "
            "'MANAGEROO deterministic fixture completed\\n')\n\n"
            "if __name__ == '__main__': unittest.main()\n",
            encoding="utf-8",
        )
        for argv in (["git", "add", "-A"], ["git", "commit", "-m", "fixture"]):
            result = runner.run(argv, cwd=repo, timeout_seconds=30)
            if not result.passed:
                raise RuntimeError(result.stderr)

        initialize_project(repo, agent="mock")
        bin_dir = Path(temp) / "bin"
        bin_dir.mkdir()
        gbrain = bin_dir / "gbrain"
        gbrain.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "import sys\n\n"
            f"repo = {json.dumps(str(repo))}\n"
            "argv = sys.argv[1:]\n"
            "if argv == ['config', 'show']:\n"
            "    print('engine: selftest')\n"
            "    print('embedding_model: selftest')\n"
            "    print('embedding_dimensions: 1')\n"
            "    print('schema_pack: selftest')\n"
            "elif argv == ['status', '--json', '--section', 'sync']:\n"
            "    print(json.dumps({'sync': {'sources': [{"
            "'source_id': 'selftest', 'name': 'selftest', 'local_path': repo, "
            "'pages': 1, 'chunks_total': 1, 'chunks_unembedded': 0, "
            "'embedding_coverage_pct': 100}], 'unacknowledged_failures': 0}}))\n"
            "elif argv[:2] == ['call', 'query']:\n"
            "    print(json.dumps({'results': [{'source_id': 'selftest', 'text': 'GBRAIN OK'}]}))\n"
            "elif argv[:1] == ['capture']:\n"
            "    print('GBRAIN CAPTURE OK')\n"
            "else:\n"
            "    print('selftest gbrain shim')\n",
            encoding="utf-8",
        )
        gbrain.chmod(0o755)
        gitnexus = bin_dir / "gitnexus"
        gitnexus.write_text("#!/bin/sh\nprintf '%s\\n' 'GITNEXUS OK'\n", encoding="utf-8")
        gitnexus.chmod(0o755)
        autoreview = bin_dir / "autoreview"
        autoreview.write_text("#!/bin/sh\nprintf '%s\\n' 'AUTOREVIEW OK'\n", encoding="utf-8")
        autoreview.chmod(0o755)
        clawpatch = bin_dir / "clawpatch"
        clawpatch.write_text("#!/bin/sh\nprintf '%s\\n' 'CLAWPATCH OK'\n", encoding="utf-8")
        clawpatch.chmod(0o755)
        old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = str(bin_dir) + os.pathsep + old_path
        config_path = repo / ".manageroo" / "config.toml"
        text = config_path.read_text(encoding="utf-8")
        gbrain_probe = bin_dir / "gbrain-readiness-probe"
        gitnexus_probe = bin_dir / "gitnexus-readiness-probe"
        for probe in (gbrain_probe, gitnexus_probe):
            probe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            probe.chmod(0o755)
        text = text.replace(
            "gbrain_readiness_probe_command = []",
            "gbrain_readiness_probe_command = " + _toml_array([str(gbrain_probe)]),
        )
        text = text.replace(
            "gitnexus_readiness_probe_command = []",
            "gitnexus_readiness_probe_command = " + _toml_array([str(gitnexus_probe)]),
        )
        if "[[verification.gates]]" not in text:
            text += (
                "\n[[verification.gates]]\n"
                'id = "fixture-check"\n'
                'kind = "test"\n'
                "required = true\n"
                "timeout_seconds = 60\n"
                "argv = ["
                + json.dumps(sys.executable)
                + ', "-m", "unittest", "discover"]\n'
            )
        else:
            text = text.replace('id = "unittest"', 'id = "fixture-check"')
        config_path.write_text(text, encoding="utf-8")

        brief = repo / ".manageroo" / "PRODUCT-BRIEF.md"
        brief.write_text(
            "# Product request\n\n"
            "Create `manageroo_fixture.txt` with the deterministic fixture text.\n",
            encoding="utf-8",
        )
        try:
            result = Orchestrator(repo, adapter=MockAdapter()).run(
                brief_path=brief,
                mode="build",
                apply_on_success=True,
            )
        finally:
            os.environ["PATH"] = old_path
        target = repo / "manageroo_fixture.txt"
        return {
            "ok": result["status"] == "COMPLETE" and target.exists(),
            "status": result["status"],
            "run_id": result["run_id"],
            "target_exists": target.exists(),
            "target_contents": target.read_text(encoding="utf-8") if target.exists() else None,
        }
