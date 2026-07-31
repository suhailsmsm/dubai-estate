#!/usr/bin/env bash
# Push dubai-estate to GitHub and trigger the Windows .exe build.
#
# Run from the dubai-estate/ directory:
#   bash tools/push-to-github.sh
#
# What it does:
#   1. Installs the GitHub CLI (gh) if missing (via Homebrew on macOS).
#   2. Logs you into GitHub (opens a browser if not already authed).
#   3. Creates a PRIVATE repo named dubai-estate under your account.
#   4. Pushes the main branch.
#   5. Triggers the "Build Electron Installer" workflow.
#
# After it finishes you can:
#   - Watch the build:  gh run watch   (or the Actions tab in the browser)
#   - Download the exe: gh run download <run-id>   (once it's green)
# Or just grab it from the Actions tab → latest run → Artifacts.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> 1/5  Checking GitHub CLI…"
if ! command -v gh >/dev/null 2>&1; then
  echo "   gh not found — installing via Homebrew…"
  if ! command -v brew >/dev/null 2>&1; then
    echo "   ERROR: Homebrew not installed. Install gh manually:"
    echo "     https://cli.github.com/manual/installation"
    exit 1
  fi
  brew install gh
fi
echo "   gh: $(gh --version | head -1)"

echo "==> 2/5  Checking GitHub auth…"
if ! gh auth status >/dev/null 2>&1; then
  echo "   Not logged in — starting login (a browser will open)…"
  gh auth login --web --git-protocol https
fi
echo "   Logged in as: $(gh api user --jq .login)"

REPO="dubai-estate"
echo "==> 3/5  Creating repo '$REPO' (private)…"
if gh repo view "$REPO" >/dev/null 2>&1; then
  echo "   repo already exists — skipping creation"
else
  gh repo create "$REPO" --private --source=. --remote=origin --description "Dubai real estate analytics: pricing history + AI market assistant (DeepSeek)"
fi

# Ensure the remote is set (in case repo existed without a remote)
git remote remove origin 2>/dev/null || true
gh repo set-default "$REPO"
git remote add origin "https://github.com/$(gh api user --jq .login)/$REPO.git"

echo "==> 4/5  Pushing main branch…"
git push -u origin main

echo "==> 5/5  Triggering the Electron Windows build…"
# workflow_dispatch needs the workflow file on the default branch first, which
# the push above just accomplished.
gh workflow run build-electron.yml || echo "   (could not auto-trigger — run it from the Actions tab)"

echo ""
echo "========================================================"
echo " Done. Watch the build:"
echo "   gh run watch"
echo " or open: $(gh repo view --web --no-browser 2>/dev/null || echo 'the Actions tab')"
echo ""
echo " When it's green, download the exe:"
echo "   gh run download <run-id>"
echo "========================================================"
