# Uncle Matt's Project Manageroo repository

This repository implements the MANAGEROO controller.

Before editing:

1. Read `docs/ARCHITECTURE.md`, `docs/ENFORCEMENT_MATRIX.md`, and `docs/LIMITATIONS.md`.
2. Run `python -m unittest discover -s tests -v`.
3. Preserve the stdlib-only runtime dependency policy.
4. Never introduce `shell=True`.
5. Update tests and documentation with behavior changes.
6. Run `python scripts/verify_release.py` before completion.

The controller must remain thin. Do not embed a new IDE, model runtime, memory database, code graph database, or marketplace. Integrate required stack systems through explicit adapters and hard readiness gates; other integrations must be explicit and must not weaken the required stack.
