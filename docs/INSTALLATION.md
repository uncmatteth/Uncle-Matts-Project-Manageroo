# Installation

## Requirements

- Python 3.11 or newer
- Git
- Internet access if Codex must be installed or updated

Install Python 3.11+ and Git with the normal package manager for the machine before running UMSMFBURASBOFE.

## Install

```bash
./install.sh
```

PowerShell users can run `.\install.ps1`; it starts the same installer.

## Installer controls

```bash
./install.sh --no-music
./install.sh --no-animation
./install.sh --skip-codex
./install.sh --skip-tests
```

The normal installation uses none of these bypasses.

## Validate

```bash
umsmfburasbofe --version
umsmfburasbofe banner --no-animation
umsmfburasbofe self-test
```

## Initialize a Git-backed project

```bash
cd /absolute/path/to/product
umsmfburasbofe init --agent codex
umsmfburasbofe doctor
```

No IDE-specific directory is created.

## Uninstall

```bash
rm -rf "$HOME/.local/share/umsmfburasbofe"
rm -f "$HOME/.local/bin/umsmfburasbofe" "$HOME/.local/bin/umsmfburasbofe.cmd"
```


## Source checkout versus release archive

A GitHub checkout and an extracted release archive use the same installer. The GitHub repository is the source of truth; a release archive is a versioned convenience copy for end users.
