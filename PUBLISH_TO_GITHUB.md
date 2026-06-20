# Publish UMSMFBURASBOFE to GitHub

Use the **GitHub source repository ZIP**, not the end-user release ZIP, for the initial repository contents.

Recommended repository name:

```text
Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
```

## 1. Create an empty GitHub repository

Create it without a generated README, license, or `.gitignore`, because those files already exist in this source tree.

Keep it private while performing the first live Codex validation. Change visibility only after the validation result is acceptable.

## 2. Extract the source ZIP and push it

```bash
unzip UMSMFBURASBOFE-GitHub-Source-v2026.6.20.1.zip
cd Uncle-Matts-Super-Mega-Forward-Build-Ultimate-Remix-All-Star-Booty-of-Fire-Edition
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

## 3. Confirm GitHub Actions

Wait for the included `verify` workflow to pass before creating a release.

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
