# Releasing the JIRA connector

This is the release runbook for the Trend Vision One JIRA connector. It is written
so either a human or an AI agent can follow it end to end. Versioning is automatic:
you never hand-edit a version string in any file.

## How it works

- Versions live in git tags shaped `jira-v<MAJOR>.<MINOR>.<PATCH>` (e.g. `jira-v1.0.0`).
- Pushing such a tag triggers `.github/workflows/jira-release.yml`, which:
  1. Derives the version from the tag (`jira-v1.0.0` -> `1.0.0`).
  2. Writes `JIRA/VERSION` and packages `JIRA/` into `tm-v1-jira-connector.tar.gz`.
  3. Publishes a versioned GitHub release for the tag.
  4. Refreshes the moving `jira-latest` release so the README download link
     always serves the newest build.
- The README download link is stable and JIRA-specific:
  `https://github.com/trendmicro/tm-v1-connectors/releases/download/jira-latest/tm-v1-jira-connector.tar.gz`

## Release flow

1. Land all code + doc changes on `main` first (via PR). Do NOT tag an unmerged branch.
2. From an up-to-date `main`, run the helper — it computes the next version for you:
   ```
   cd JIRA
   ./release.sh          # patch bump (default): 1.0.0 -> 1.0.1
   ./release.sh minor    # 1.0.1 -> 1.1.0
   ./release.sh major    # 1.1.0 -> 2.0.0
   ./release.sh 2.3.4    # explicit version, if ever needed
   ```
   The script fetches tags, finds the highest `jira-v*`, bumps it, confirms, then
   pushes the new tag. First-ever release starts at `1.0.0`.
3. Watch the run: https://github.com/trendmicro/tm-v1-connectors/actions
4. Verify the release and the download link resolve:
   - Versioned: `https://github.com/trendmicro/tm-v1-connectors/releases/tag/jira-v<version>`
   - Latest link (README): downloads `tm-v1-jira-connector.tar.gz`

## Choosing the bump

- `patch` — bug fix only, no behavior change (default).
- `minor` — backward-compatible feature or config addition.
- `major` — breaking change to config or behavior.

## Notes

- The `jira-latest` link 404s until the first `jira-v*` tag is published; that is expected.
- The workflow packages only `JIRA/`; other connectors in this monorepo are unaffected.
