"""Bootstrap the repository's src-layout package before unittest discovery."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if _SRC.is_dir():
    src_text = str(_SRC)
    sys.path[:] = [entry for entry in sys.path if entry != src_text]
    sys.path.insert(0, src_text)


class BootstrapTests(unittest.TestCase):
    def test_repository_source_precedes_an_installed_package(self):
        root = Path(__file__).resolve().parents[1]
        probe = textwrap.dedent(
            """
            import runpy
            import sys
            from pathlib import Path

            repo_src = Path(sys.argv[1]).resolve()
            bootstrap = Path(sys.argv[2]).resolve()
            fake_root = Path(sys.argv[3]).resolve()
            sys.path[:] = [
                entry
                for entry in sys.path
                if Path(entry or ".").resolve() != repo_src
            ]
            sys.path.insert(0, str(fake_root))
            sys.path.append(str(repo_src))
            runpy.run_path(str(bootstrap), run_name="_manageroo_bootstrap_probe")

            import manageroo

            origin = Path(manageroo.__file__).resolve()
            if not origin.is_relative_to(repo_src):
                raise SystemExit(f"manageroo imported from {origin}, not {repo_src}")
            """
        )
        bootstraps = (
            "tests/__init__.py",
            "tests/conftest.py",
            "tests/test_000_bootstrap.py",
        )
        with tempfile.TemporaryDirectory() as temp:
            fake_root = Path(temp) / "site-packages"
            fake_package = fake_root / "manageroo"
            fake_package.mkdir(parents=True)
            (fake_package / "__init__.py").write_text("FAKE = True\n", encoding="utf-8")
            for relative in bootstraps:
                with self.subTest(bootstrap=relative):
                    result = subprocess.run(
                        [
                            sys.executable,
                            "-c",
                            probe,
                            str(root / "src"),
                            str(root / relative),
                            str(fake_root),
                        ],
                        cwd=root,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
