# Publish UMSMFBURASBOFE to GitHub

Use the source tree for the GitHub repository. If you start from a ZIP, extract it
first and commit the files; do not commit the ZIP as the repository contents.

Recommended repository name:

```text
Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
```

## 1. Create an empty GitHub repository

Create it without a generated README, license, or `.gitignore`, because those files already exist in this source tree.

Keep it private while performing the first live agent validation. Change visibility only after the validation result is acceptable.

## 2. Push the source tree

If you are using the prepared `GitHub-Upload` folder, start inside that folder.
If you are starting from a source ZIP, extract it first:

```bash
unzip UMSMFBURASBOFE-GitHub-Source-v2026.6.20.1.zip
cd Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
```

Then push the source tree:

```bash
git init -b main
git add .
git commit -m "Initial UMSMFBURASBOFE source release"
git remote add origin https://github.com/uncmatteth/Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition.git
git push -u origin main
```

Use an SSH remote instead when that is how GitHub authentication is configured:

```bash
git remote set-url origin git@github.com:uncmatteth/Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition.git
```

## 3. Confirm the local release checks

This repository does not use GitHub Actions. Before creating a release, run
the local verification command and use the generated checksums:

```bash
python3 scripts/verify_release.py
python3 scripts/package_release.py
```

Do not publish a release ZIP that contains `.github/workflows/`.

## 4. Create the first release

Suggested tag:

```text
v2026.6.20.1
```

Attach these files to the GitHub Release:

```text
UMSMFBURASBOFE-End-User-Release-v2026.6.20.1.zip
UMSMFBURASBOFE-Release-SHA256SUMS.txt
```

The source repository itself remains browsable through GitHub. The release ZIP is the convenient installer package for end users.

## 5. Public one-line install commands

After the repository is public:

```bash
git clone --depth 1 https://github.com/uncmatteth/Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition.git && cd Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition && ./install.sh
```

## 6. Do not publish credentials

Before changing repository visibility, verify that no `.umsmfburasbofe/runs/`, local environment files, credentials, private product briefs, or target-project data have been copied into this source repository.
