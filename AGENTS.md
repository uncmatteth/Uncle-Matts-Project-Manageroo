# Uncle Matt's Project Manageroo repository

This repository implements the MANAGEROO controller.

Before editing:

1. Read `docs/ARCHITECTURE.md`, `docs/ENFORCEMENT_MATRIX.md`, and `docs/LIMITATIONS.md`.
2. Run `PYTHONPATH=src python3 -m unittest discover -s tests -v`.
3. Preserve the stdlib-only runtime dependency policy.
4. Never introduce `shell=True`.
5. Update tests and documentation with behavior changes.
6. Run `python3 scripts/verify_release.py` before completion.
7. Do not add GitHub Actions or files under `.github/workflows/`; release proof stays local.

The controller must remain thin. Do not embed a new IDE, model runtime, memory database, code graph database, or marketplace. Integrate such systems through explicit optional adapters.
