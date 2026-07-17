# Publish MANAGEROO to GitHub

Use the source tree for the GitHub repository. If you start from a ZIP, extract it
first and commit the files; do not commit the ZIP as the repository contents.

Recommended repository name:

```text
Uncle-Matts-Project-Manageroo
```

## 1. Create an empty GitHub repository

Create it without a generated README, license, or `.gitignore`, because those files already exist in this source tree.

Keep it private while performing the first live agent validation. Change visibility only after the validation result is acceptable.

## 2. Push the source tree

If you are using the local source checkout, start inside that repository folder.
If you are starting from a source ZIP, extract it first:

```bash
unzip uncle-matts-project-manageroo-v2026.7.17.2-source.zip
cd Uncle-Matts-Project-Manageroo
```

Then push the source tree:

```bash
git init -b main
git add .
git commit -m "Initial MANAGEROO source release"
git remote add origin https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git
git push -u origin main
```

Use an SSH remote instead when that is how GitHub authentication is configured:

```bash
git remote set-url origin git@github.com:uncmatteth/Uncle-Matts-Project-Manageroo.git
```

## 3. Run the fail-closed release command

This repository does not use GitHub Actions. Before creating a release, run:

```bash
python3 scripts/release.py
```

That one command performs the required sequence:

1. `manageroo prove --json` with an automatically selected installed live coding worker;
2. the complete source regression and structural verifier;
3. release packaging and checksum generation;
4. clean-install end-user ZIP smoke testing;
5. drop-folder assembly.

The command refuses to package unless product proof reports `COMPLETE`.

To force a particular installed live worker:

```bash
python3 scripts/release.py --live-agent codex
python3 scripts/release.py --live-agent claude-code
python3 scripts/release.py --live-agent gemini
```

The lower-level commands remain available for diagnosis:

```bash
manageroo prove
python3 scripts/verify_release.py
python3 scripts/package_release.py
```

`manageroo prove` may report `COMPLETE` only when all required adversarial, regression, outcome-proof, and live-worker lanes pass.

Do not publish a release ZIP that contains `.github/workflows/`.

Run the generated release ZIP smoke on each operating system you claim to support. The same smoke script selects `install.sh` on Unix-like systems and `install.ps1` on Windows:

```bash
python3 scripts/smoke_release_install.py --archive /path/to/uncle-matts-project-manageroo-v2026.7.17.2.zip
```

A passing smoke on one operating system is proof only for that operating system.

## 4. Create the release

Suggested tag:

```text
v2026.7.17.2
```

Attach every generated drop-folder file to the GitHub Release, because
`SHA256SUMS.txt` lists the full drop set:

```text
uncle-matts-project-manageroo-v2026.7.17.2.zip
uncle-matts-project-manageroo-v2026.7.17.2-source.zip
SHA256SUMS.txt
SOURCE-VALIDATION.json
FINAL-VALIDATION.json
LOCAL-SETUP.md
PUBLISH-TO-GITHUB.md
GIVE-THIS-TO-YOUR-IDE-AGENT.md
GITHUB-DESCRIPTION.md
```

The source repository itself remains browsable through GitHub. The release ZIP
is the convenient installer package for end users; the source ZIP and helper
docs make the release self-contained.

## 5. Public one-line install commands

After the repository is public:

```bash
git clone --depth 1 https://github.com/uncmatteth/Uncle-Matts-Project-Manageroo.git && cd Uncle-Matts-Project-Manageroo && ./install.sh
```

## 6. Do not publish credentials

Before changing repository visibility, verify that no `.manageroo/runs/`, local environment files, credentials, private product briefs, or target-project data have been copied into this source repository.
