#!/usr/bin/env bash
#
# Release helper for the Trend Vision One JIRA connector.
#
# Auto-computes the next version from existing "jira-v*" tags, creates the tag,
# and pushes it. Pushing the tag triggers .github/workflows/jira-release.yml,
# which packages JIRA/ and publishes the GitHub release.
#
# Usage:
#   ./release.sh            # bump patch  (jira-v1.0.0 -> jira-v1.0.1)
#   ./release.sh minor      # bump minor  (jira-v1.0.1 -> jira-v1.1.0)
#   ./release.sh major      # bump major  (jira-v1.1.0 -> jira-v2.0.0)
#   ./release.sh 2.3.4       # set an explicit version
#
set -euo pipefail

TAG_PREFIX="jira-v"
BUMP="${1:-patch}"

# Ensure local tags are up to date with the remote before computing the next one.
git fetch --tags --quiet

# Find the highest existing jira-v* version (empty if this is the first release).
latest="$(git tag -l "${TAG_PREFIX}*" | sed "s/^${TAG_PREFIX}//" | sort -V | tail -n1)"

if [[ "${BUMP}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  # Explicit version supplied.
  next="${BUMP}"
else
  if [[ -z "${latest}" ]]; then
    # No prior release: start at 1.0.0 regardless of bump type.
    next="1.0.0"
  else
    IFS='.' read -r major minor patch <<<"${latest}"
    case "${BUMP}" in
      major) major=$((major + 1)); minor=0; patch=0 ;;
      minor) minor=$((minor + 1)); patch=0 ;;
      patch) patch=$((patch + 1)) ;;
      *) echo "Unknown bump type: ${BUMP} (use major|minor|patch or an explicit X.Y.Z)" >&2; exit 1 ;;
    esac
    next="${major}.${minor}.${patch}"
  fi
fi

tag="${TAG_PREFIX}${next}"

if git rev-parse -q --verify "refs/tags/${tag}" >/dev/null; then
  echo "Tag ${tag} already exists. Aborting." >&2
  exit 1
fi

echo "Current latest: ${latest:-<none>}"
echo "New release   : ${tag}"
read -r -p "Create and push ${tag}? [y/N] " confirm
if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
  echo "Aborted."
  exit 0
fi

git tag -a "${tag}" -m "JIRA connector ${next}"
git push origin "${tag}"

echo "Pushed ${tag}. GitHub Actions is now building and publishing the release."
echo "Track it: https://github.com/trendmicro/tm-v1-connectors/actions"
