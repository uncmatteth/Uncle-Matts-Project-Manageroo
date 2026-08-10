# Final handoff

## Install

macOS/Linux:

```bash
./install.sh
```

Windows PowerShell:

```powershell
.\install.ps1
```

## Verify

```bash
manageroo --version
manageroo self-test
```

## Initialize a product repository

```bash
cd /absolute/path/to/product
manageroo init --agent codex
manageroo doctor
```

Do not continue until `doctor` reports `READY`.

## Build

```bash
manageroo run --repo . --mode build --brief .manageroo/PRODUCT-BRIEF.md --apply
```

## Repair

```bash
manageroo run --repo . --mode repair --brief .manageroo/PRODUCT-BRIEF.md --apply
```

Only a durable controller state of `COMPLETE` authorizes final patch application.
