## Trend Vision One™ JIRA connector

#### Download
Latest packaged release (always points to the newest build):
- [tm-v1-jira-connector.tar.gz](https://github.com/trendmicro/tm-v1-connectors/releases/download/jira-latest/tm-v1-jira-connector.tar.gz)

Extract it, then follow the Quick start below:
```
tar -xzf tm-v1-jira-connector.tar.gz
```

#### Prerequisites
- [Python 3.8](https://www.python.org/downloads/) or newer.
- JIRA API url.
- JIRA username/token.
- Trend Vision One API url. 
- Trend Vision One API token with permissions: 
  - View, filter, and search
  - Modify alert details

#### Features
- Create issue from Trend Vision One workbench alerts.
- Add issue number to the workbench alert notes.
- Update issue based on workbench alert status/jira status mapping.
- Map issue fields to static data/vision one attributes.
 
#### Quick start
- Installation:
  ```
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt
  ```
- Configuration:
  - Edit [config.yml](config.yml).

- Start application:
  ```
  python3 app.py
  ```

#### YAML Configuration
The configuration of this project is based on YAML config file [config.yml](config.yml).
##### General
| yaml           | description                                                                                  |
|:---------------|:---------------------------------------------------------------------------------------------|
| project        | JIRA Project ID or key.                                                                      |
| issue_type     | JIRA Issue type ID or name.                                                                  |
| summary_prefix | (Optional) JIRA Issue summary prefix.                                                        |
| poll_time      | Skip closed alerts in Vision One, else create a new JIRA and re-open the alert.              |
| start_time     | (Optional) Alerts fetch start time (UTC timezone), defaults to the time the request is made. |
| end_time       | (Optional) Alerts fetch end time (UTC timezone), defaults to the time the request is made.   |
| skip_closed    | Skip closed alerts in Vision One, else create a new JIRA and re-open the alert.              |
| debug          | Enable debug logging.                                                                        |
| to_file        | Enable logging to file instead of stdout.                                                    |
| filename       | Log filename.                                                                                |
| file_size      | Log file max size in MB.                                                                     |
| file_count     | Log files rotation count.                                                                    |
##### Vision One
| yaml     | description           |
|:---------|:----------------------|
| v1.url   | Vision One API URL.   |
| v1.token | Vision One API Token. | 

##### JIRA
| yaml          | description                                                                                                 |
|:--------------|:------------------------------------------------------------------------------------------------------------|
| jira.url      | JIRA URL.                                                                                                   |
| jira.username | JIRA Cloud Username (User email address associated to the API Token), If using JIRA On-premise leave empty. |
| jira.token    | JIRA Cloud API Token or On-premise Personal Authentication Token.                                           |

##### Mapping: [JIRA issue fields] to [Static data] OR [Vision One attributes mapping]
- Map JIRA field to: static values, or to Vision One alert attributes returned by [Get alert details API](https://automation.trendmicro.com/xdr/api-v3#tag/Workbench/paths/~1v3.0~1workbench~1alerts/get).
- (Optional) mapping available to map multiple JIRA values with Vision One attributes values. (i.e: priority 'P3' in JIRA mapped to Vision One severity 'low').

| yaml               | description                                                                                                                                           |
|:-------------------|:------------------------------------------------------------------------------------------------------------------------------------------------------|
| fields[].name      | JIRA field name or key (i.e: priority, label, customfield_12345, ...).                                                                                |
| fields[].value([]) | JIRA field value(s) (i.e: 2345, Option 1, email@address.com, ...) or Vision One attribute (i.e: alert.id, alert.alert_provider, alert.severity, ...). |
| fields[].mapping   | (Optional) JIRA-Vision one field value mapping (i.e: P3: low).                                                                                        |

##### Mapping: [JIRA issue status] to [Vision One Alert investigation status]
| yaml                | description                                                    |
|:--------------------|:---------------------------------------------------------------|
| status[].name       | JIRA status name (i.e: To Do, Done, ...).                      |
| status[].inv        | Vision One Alert investigation status (i.e: New, Closed, ...). |
| status[].fields([]) | (Optional) JIRA field name/value mapping as described above.   |
