#!/usr/bin/env bash
# bump-version.sh [patch|minor]
#
# Bumps the version in pyproject.toml and ixl_cli/__init__.py,
# then commits the change.
#
# Strategy:
#   patch  — bug fixes (fix: commits)
#   minor  — new features (feat: commits)
#   1.0.0  — manual only, when CLI contract is stable

set -euo pipefail

TYPE="${1:-patch}"
REPO_ROOT="$(git rev-parse --show-toplevel)"
PYPROJECT="$REPO_ROOT/pyproject.toml"
INIT="$REPO_ROOT/ixl_cli/__init__.py"

# Read current version
CURRENT=$(grep '^version = ' "$PYPROJECT" | sed 's/version = "\(.*\)"/\1/')
MAJOR=$(echo "$CURRENT" | cut -d. -f1)
MINOR=$(echo "$CURRENT" | cut -d. -f2)
PATCH=$(echo "$CURRENT" | cut -d. -f3)

case "$TYPE" in
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  patch)
    PATCH=$((PATCH + 1))
    ;;
  *)
    echo "Usage: bump-version.sh [patch|minor]" >&2
    exit 1
    ;;
esac

NEW="${MAJOR}.${MINOR}.${PATCH}"

echo "Bumping version: $CURRENT → $NEW ($TYPE)"

# Update pyproject.toml
sed -i "s/^version = \"$CURRENT\"/version = \"$NEW\"/" "$PYPROJECT"

# Update __init__.py
sed -i "s/__version__ = \"$CURRENT\"/__version__ = \"$NEW\"/" "$INIT"

# Commit
git add "$PYPROJECT" "$INIT"
git commit -m "chore: bump version to $NEW"
