## Trend Vision One™ JIRA connector

A standalone poller that keeps Trend Vision One workbench alerts and JIRA issues
in sync. It creates a JIRA issue for each new workbench alert and keeps the alert
status and the issue status aligned in both directions.

### Contents
- [How it works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Supported JIRA versions](#supported-jira-versions)
- [Download](#download)
- [Quick start](#quick-start)
- [Authentication](#authentication)
- [Configuration](#configuration)
  - [General](#general)
  - [Vision One](#vision-one)
  - [JIRA](#jira)
  - [Field mapping](#field-mapping-jira-fields---static-values-or-vision-one-attributes)
  - [Status mapping](#status-mapping-jira-status---vision-one-alert-status)
- [Full config example](#full-config-example)
- [Troubleshooting](#troubleshooting)

---

### How it works
Every `poll_time` seconds the connector:

1. Fetches workbench alerts from Vision One in the configured time window.
2. For a **new** alert (not seen before), creates a JIRA issue with the mapped
   fields and description, attaches the raw alert JSON, and writes a note back
   to the Vision One alert with the issue key.
3. For a **known** alert (already has an issue), compares the JIRA status and the
   Vision One alert status and, if they differ, syncs the side that changed
   **last** (by last-updated timestamp):
   - JIRA changed more recently -> update the Vision One alert status.
   - Vision One changed more recently -> transition the JIRA issue.

Processed alerts are tracked in a local `.cache` file (`alertId:issueKey`) to
avoid duplicate issues.

Status sync is driven by the Vision One Alert **status** (`Open`, `In Progress`,
`Closed`) - the workbench alert lifecycle status shown in the Vision One console.
The deprecated *investigation status* is not used: a closed alert reports an
investigation *result* (e.g. `True Positive`), which is a separate field.

### Prerequisites
- [Python 3.8](https://www.python.org/downloads/) or newer.
- JIRA base URL and credentials (see [Authentication](#authentication)).
- Trend Vision One API URL.
- Trend Vision One API token with permissions:
  - View, filter, and search
  - Modify alert details

### Supported JIRA versions
Targets **on-premise JIRA (Server / Data Center) 9.x and newer** via the JIRA
REST API v2 (`/rest/api/2/...`). JIRA Cloud is also supported using Cloud
API-token (basic) authentication.

### Download
Latest packaged release (always points to the newest build):
- [tm-v1-jira-connector.tar.gz](https://github.com/trendmicro/tm-v1-connectors/releases/download/jira-latest/tm-v1-jira-connector.tar.gz)

Extract it:
```
tar -xzf tm-v1-jira-connector.tar.gz
```

### Quick start
1. Install:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```
2. Configure: edit [config.yml](config.yml) (see [Configuration](#configuration)).
3. Run:
   ```
   python3 app.py
   ```
   The connector runs continuously, polling every `poll_time` seconds. Run it
   under a process manager (systemd, supervisor, ...) for unattended use.

### Authentication
The connector auto-selects the auth scheme from `jira.username`:

| Deployment             | `jira.username`       | `jira.token`                | Header sent      |
|:-----------------------|:----------------------|:----------------------------|:-----------------|
| On-premise (Server/DC) | leave **empty**       | Personal Access Token (PAT) | `Bearer <token>` |
| Cloud                  | account email address | Cloud API token             | `Basic <base64>` |

Vision One authenticates with an API token (`v1.token`).

> The auth mode also changes how user fields (`reporter`, `assignee`) are sent:
> on-premise uses the JIRA **username**, Cloud uses the **accountId**. See
> [Field mapping](#field-mapping-jira-fields---static-values-or-vision-one-attributes).

### Configuration
All configuration is in the YAML file [config.yml](config.yml).

#### General
| yaml           | description                                                                                   |
|:---------------|:----------------------------------------------------------------------------------------------|
| project        | JIRA Project ID or key.                                                                        |
| issue_type     | JIRA Issue type ID or name (e.g. `Bug`).                                                       |
| summary_prefix | (Optional) Prefix prepended to the issue summary. Leave empty to omit.                         |
| poll_time      | Seconds to wait between polling cycles.                                                        |
| start_time     | (Optional) Alerts fetch start time, UTC (e.g. `2025-08-07 08:20:00`). Defaults to 24h before the request. Max lookback 30 days. |
| end_time       | (Optional) Alerts fetch end time, UTC. Defaults to the time the request is made.               |
| skip_closed    | `true`: ignore alerts already `Closed` in Vision One. `false`: create an issue and re-open them. |
| debug          | Enable debug logging.                                                                          |
| to_file        | Log to a rotating file instead of stdout.                                                      |
| filename       | Log filename (when `to_file`).                                                                 |
| file_size      | Log file max size in MB.                                                                        |
| file_count     | Number of rotated log files to keep.                                                           |

#### Vision One
| yaml     | description         |
|:---------|:--------------------|
| v1.url   | Vision One API URL. |
| v1.token | Vision One API token. |

#### JIRA
| yaml          | description                                                                        |
|:--------------|:-----------------------------------------------------------------------------------|
| jira.url      | JIRA base URL.                                                                      |
| jira.username | Cloud: the account email tied to the API token. On-premise: **leave empty**.       |
| jira.token    | Cloud API token, or on-premise Personal Access Token (PAT).                         |

#### Field mapping: [JIRA fields] -> [static values] OR [Vision One attributes]
Map a JIRA field to a static value, or to a Vision One alert attribute returned
by the [Get alert details API](https://automation.trendmicro.com/xdr/api-v3#tag/Workbench/paths/~1v3.0~1workbench~1alerts/get)
(prefix with `alert.`, e.g. `alert.id`, `alert.severity`, `alert.alert_provider`).

| yaml               | description                                                                                                                                     |
|:-------------------|:----------------------------------------------------------------------------------------------------------------------------------------------|
| fields[].name      | JIRA field name or key (e.g. `priority`, `labels`, `customfield_12345`).                                                                       |
| fields[].value([]) | A static value, or a Vision One attribute (`alert.*`). May be a list. For user fields (`reporter`, `assignee`) use the JIRA **username** on-premise, the **accountId** on Cloud. |
| fields[].mapping   | (Optional) Translate a Vision One value to a JIRA value. Written as `JIRA_value: vision_one_value` (e.g. `High: high`).                        |

Notes:
- Any JIRA field that is **required** for your issue type must be present here
  (e.g. `reporter` is often required). Missing required fields fail issue creation.
- `mapping` values must match the exact Vision One attribute value. Severity
  values are lowercase: `critical`, `high`, `medium`, `low`.

#### Status mapping: [JIRA status] -> [Vision One Alert status]
This table drives the two-way status sync.

| yaml                | description                                                                                                                                    |
|:--------------------|:---------------------------------------------------------------------------------------------------------------------------------------------|
| status[].name       | JIRA status name, exactly as it appears in your workflow (case-insensitive).                                                                   |
| status[].inv        | Vision One Alert status: `Open`, `In Progress`, or `Closed`. The legacy value `New` is accepted as an alias for `Open`.                        |
| status[].inv_result | (Optional) Vision One investigation result set on the JIRA -> Vision One sync. **Required when `inv` is `Closed`** (Vision One rejects closing an alert without a result). One of: `No Findings`, `Noteworthy`, `True Positive`, `False Positive`, `Benign True Positive`. If omitted, an `investigationResult` entry under `fields` is used as a fallback. |
| status[].fields([]) | (Optional) Extra JIRA fields set during the JIRA transition (Vision One -> JIRA direction), e.g. a resolution when closing. Same shape as [Field mapping](#field-mapping-jira-fields---static-values-or-vision-one-attributes). |

**Important - the mapping must cover your whole workflow:**

- Vision One has exactly three alert statuses (`Open`, `In Progress`, `Closed`).
  Map **each of the three** so the Vision One -> JIRA direction always has a
  target JIRA status.
- List **every JIRA status an issue can be in**, not just three. If an issue sits
  in an unmapped status (e.g. a `Selected for Development` or a review column your
  workflow adds), the sync for that issue is skipped and logged as
  *"JIRA status not mapped"*. Add every reachable status.
- The JIRA status names must match your workflow. The bundled sample uses the
  generic `To Do` / `In Progress` / `Done`; a real workflow often differs
  (localized names, extra columns, a service-desk workflow). Adjust to yours.
- Avoid mapping **more than one** JIRA status to the same `inv` value. The
  Vision One -> JIRA direction transitions to the **first** matching entry, so
  duplicates make that direction ambiguous.
- When closing (`inv: Closed`), provide `inv_result`. If your close transition
  screen requires a resolution, also add it under `fields`.

Worked example - a workflow with an extra `Selected for Development` column and a
`Backlog` start state, all mapped:
```yaml
status:
  - name: Backlog
    inv: Open
  - name: Selected for Development
    inv: In Progress
  - name: In Progress
    inv: In Progress            # NOTE: two JIRA statuses -> In Progress.
                                # V1 -> JIRA will pick "Selected for Development"
                                # (first match). Prefer one JIRA status per inv.
  - name: Done
    inv: Closed
    inv_result: True Positive
    fields:
      - name: Resolution        # only if your close transition screen asks for it
        value: Done
```

### Full config example
See [config.yml](config.yml) for a complete, commented sample.

### Troubleshooting
| Symptom (log / API error) | Cause | Fix |
|:--------------------------|:------|:----|
| Vision One error `3090003` "Unable to process the request" on status update | Old `pytmv1`; incompatible alert-status API | Use the shipped `requirements.txt` (`pytmv1~=0.11.0`). |
| `JIRA status not mapped` / `Vision One ... status not mapped` | An in-use JIRA status (or an alert status) is missing from `status:` | Add every reachable JIRA status; map all three Vision One statuses. See [Status mapping](#status-mapping-jira-status---vision-one-alert-status). |
| Closing does not sync / "requires an investigation result" | `inv: Closed` without `inv_result` | Add `inv_result` (e.g. `True Positive`) to the Closed entry. |
| Issue creation fails on `reporter`/`assignee` | Wrong user identifier for the deployment | On-premise: leave `jira.username` empty and use the JIRA **username** as the field value. Cloud: use the **accountId**. |
| `... field cannot be set. It is not on the appropriate screen` | A `fields` entry (e.g. `Resolution`) is not on the transition screen | Add the field to the JIRA transition screen, or remove it from `fields`. |
| Issue creation blocked by license | JIRA license invalid/expired | Renew the JIRA license. |
