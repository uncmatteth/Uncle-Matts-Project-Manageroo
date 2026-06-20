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
umsmfburasbofe --version
umsmfburasbofe self-test
```

## Initialize a product repository

```bash
cd /absolute/path/to/product
umsmfburasbofe init --agent codex
umsmfburasbofe doctor
```

Do not continue until `doctor` reports `READY`.

## Build

```bash
umsmfburasbofe run --repo . --mode build --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

## Repair

```bash
umsmfburasbofe run --repo . --mode repair --brief .umsmfburasbofe/PRODUCT-BRIEF.md --apply
```

Only a durable controller state of `COMPLETE` authorizes final patch application.
