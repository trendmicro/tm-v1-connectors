import base64
import dataclasses
import datetime
import logging
import logging.handlers
import os.path
import threading
import time
from enum import Enum
from functools import reduce
from typing import Any, Dict, List, Union

import pytmv1
import yaml
from pytmv1 import EntityType, InvestigationStatus, ResultCode
from requests import Request, Session

ALERT_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
ADD_ATTACHMENT = "/rest/api/2/issue/{0}/attachments"
CREATE_ISSUE = "/rest/api/2/issue"
GET_ISSUE_TYPES = "/rest/api/2/issue/createmeta/{0}/issuetypes/"
GET_FIELDS_META = "/rest/api/2/issue/createmeta/{0}/issuetypes/{1}/"
GET_MYSELF = "/rest/api/2/myself"
GET_PROJECT = "/rest/api/2/project/{0}"
GET_USER = "/rest/api/2/user/search?username={}"
DO_TRANSITION = "/rest/api/2/issue/{0}/transitions"
GET_ISSUE = "/rest/api/2/issue/{0}"
GET_LAST_UPDATED = "/rest/api/2/issue/{0}?fields=creator,updated"
GET_STATUS = "/rest/api/2/issue/{0}?fields=status"
GET_STATUSES = "/rest/api/2/project/{0}/statuses/"
GET_TRANSITIONS = "/rest/api/2/issue/{0}/transitions?expand=transitions.fields"
LOG_FORMAT = (
    "%(asctime)s %(levelname)-5s ::: %(thread)d %(filename)-18s :::"
    " %(funcName)-18s:%(lineno)-5s ::: %(id)s :::  %(message)s"
)
LOG_FORMAT_DATE = "%Y-%m-%d %H:%M:%S"

OPTIONAL_KEYS = {
    "start_time",
    "end_time",
}

_THREAD_LOCAL = threading.local()
log = logging.getLogger(__name__)


def _load_config():
    yamlcfg = _load_yaml()
    _validate_cfg_keys(yamlcfg)
    _validate_cfg_list_keys(yamlcfg)
    return yamlcfg


def _load_yaml():
    with open("config.yml", "r") as stream:
        try:
            return yaml.safe_load(stream)
        except (yaml.YAMLError, ValueError) as exc:
            log.error("Could not load config.yml file, error: %s", exc.args)
            exit(1)


def _init_logger():
    root = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT, LOG_FORMAT_DATE)
    if CFG["to_file"]:
        for handler in root.handlers:
            root.removeHandler(handler)
        handler = logging.handlers.RotatingFileHandler(
            CFG["filename"],
            maxBytes=int(CFG["file_size"]) * 1024 * 1024,
            backupCount=CFG["file_count"],
        )
        root.addHandler(handler)
    else:
        if not root.handlers:
            root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(formatter)
        handler.addFilter(UuidFilter())
    root.setLevel(logging.DEBUG if CFG["debug"] else logging.INFO)


def _load_cache():
    try:
        if os.path.isfile(".cache"):
            with open(".cache", "rt") as cache:
                cache = {
                    k.split(":")[0]: k.split(":")[1]
                    for k in cache.read().split(",")
                    if k
                }
                log.info("Loaded cache: %s", cache)
                return cache
        else:
            open(".cache", "x").close()
            log.info("Created new empty cache file [.cache]")
            return {}
    except OSError as exc:
        log.error("Could not load cache file, error: %s", exc.args)
        exit(1)


def _validate_cfg_keys(yamlcfg):
    missing_values = list(
        filter(
            lambda config_key: yamlcfg.get(config_key) is None
            and config_key not in OPTIONAL_KEYS,
            Config.__annotations__.keys(),
        )
    )
    unexpected_values = list(
        filter(
            lambda conf: conf not in Config.__annotations__.keys(),
            yamlcfg.keys(),
        ),
    )
    if missing_values or unexpected_values:
        if missing_values:
            log.error("Missing configuration key(s): %s", missing_values)
        if unexpected_values:
            log.error("Configuration key(s) does not exist: %s", unexpected_values)
        raise ValueError


def _validate_cfg_list_keys(yamlcfg):
    fields = [
        *reduce(
            lambda f1, f2: [*f1, *f2],
            map(lambda st: st.get("fields", []), yamlcfg["status"]),
        ),
        *yamlcfg["fields"],
    ]
    _validate_keys(fields, yamlcfg["status"])


def _validate_keys(fields, status):
    error = False
    configs = [
        {"config": fields, "req": ("name", "value"), "optional": ("mapping",)},
        {"config": status, "req": ("name", "inv"), "optional": ("fields",)},
    ]
    for cfg in configs:
        valid_keys = [*cfg["req"], *cfg["optional"]]
        unexpected_values = _key_not_found(cfg["config"], valid_keys)
        missing_keys = _key_missing(cfg["config"], cfg["req"])
        if unexpected_values or missing_keys:
            error = True
            if missing_keys:
                log.error("Missing configuration key(s): %s", missing_keys)
            if unexpected_values:
                log.error("Configuration key(s) does not exist: %s", unexpected_values)
            log.error("Valid keys: %s", valid_keys)
    if error:
        raise ValueError


def _key_missing(config, req_keys):
    return list(
        filter(
            lambda field: field.get("missing"),
            map(
                lambda field: {
                    "name": field.get("name"),
                    "missing": list(
                        filter(lambda rk: rk not in field.keys(), req_keys)
                    ),
                },
                config,
            ),
        )
    )


def _key_not_found(config, valid_keys):
    return list(
        filter(
            lambda field: field not in valid_keys,
            _config_keys_set(config),
        )
    )


def _config_keys_set(config):
    return reduce(
        lambda cfg1, cfg2: {*cfg1, *cfg2},
        map(lambda cfg: {*cfg.keys()}, config),
    )


class UuidFilter(logging.Filter):
    def filter(self, record):
        record.id = (
            _THREAD_LOCAL.id if hasattr(_THREAD_LOCAL, "id") and not None else "App"
        )
        return True


@dataclasses.dataclass
class Config:
    project: Union[str, int]
    issue_type: str
    summary_prefix: str
    poll_time: int
    start_time: datetime
    end_time: datetime
    skip_closed: bool
    debug: bool
    to_file: bool
    filename: str
    file_size: int
    file_count: int
    v1: Dict[str, str]
    jira: Dict[str, str]
    status: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    fields: List[Dict[str, Any]] = dataclasses.field(default_factory=list)


CFG = _load_config()
_init_logger()


class App:
    def __init__(self):
        self.cfg = Config(**CFG)
        self.cache = _load_cache()
        self.v_client = pytmv1.init(
            "v1jira",
            self.cfg.v1["token"],
            self.cfg.v1["url"],
            1,
            1,
            30,
            30,
        )
        self.j_client = Session()
        self._check_conn()
        self._map_config()
        log.info("Initialized application with config: %s", self.cfg)

    def _save_cache(self, alert_id, jira_id):
        try:
            with open(".cache", "a") as cache:
                cache.write(alert_id + ":" + jira_id + ",")
                self.cache[alert_id] = jira_id
                log.debug("Written to cache alert %s (%s)", alert_id, jira_id)
        except OSError as exc:
            log.error("Could not save to cache, error: %s", exc.args)
            exit(1)

    def _map_config(self):
        self.project = self._jira_project()
        self.issue_type = self._jira_issue_type()
        self.start_time = _format_config_time(self.cfg.start_time)
        self.end_time = _format_config_time(self.cfg.end_time)
        _map_fields_metadata(self.cfg.fields, self._jira_fields())
        _map_statuses_metadata(self.cfg.status, self._jira_statuses())

    def _send(self, method, uri, **kwargs):
        token = self.cfg.jira["token"]
        username = self.cfg.jira["username"]
        authorization = (
            f"Basic {base64.b64encode('{}:{}'.format(username, token).encode()).decode()}"
            if username
            else f"Bearer {token}"
        )
        headers = {"Authorization": authorization}
        headers.update(kwargs.pop("headers", {}))
        request = Request(
            method,
            self.cfg.jira["url"] + uri,
            headers=headers,
            **kwargs,
        )
        return self.j_client.send(
            request.prepare(),
            timeout=(60, 10),
            allow_redirects=True,
        )

    def _check_conn(self):
        v1_resp = self.v_client.system.check_connectivity()
        if v1_resp.result_code == ResultCode.ERROR:
            log.error("Connectivity to Vision One failed, error: %s", v1_resp.error)
            raise RuntimeError
        jira_resp = self._send("GET", GET_MYSELF)
        if jira_resp.status_code != 200 or 302 in (
            jr.status_code for jr in jira_resp.history
        ):
            log.error(
                "Connectivity to JIRA failed, status: %s, error: %s",
                jira_resp.status_code,
                jira_resp.content,
            )
            raise RuntimeError
        log.info("Successfully connected to Vision One and JIRA")

    def _validate_curr_statuses(self, jira_status, v1_status):
        not_found_status = jira_status not in [st["key"] for st in self.cfg.status]
        not_found_inv_status = v1_status not in [st["inv_st"] for st in self.cfg.status]
        if not_found_status or not_found_inv_status:
            if not_found_status:
                log.warning(
                    "JIRA status not mapped\nMissing config: %s\nCurrent config: %s",
                    {"name": jira_status},
                    self.cfg.status,
                )
            if not_found_inv_status:
                log.warning(
                    "Vision One investigation status not mapped\nMissing config: %s\nCurrent config: %s",
                    {"inv": v1_status.value},
                    self.cfg.status,
                )
            raise ValueError

    def _get_config_status_by(self, status, key):
        return next(
            filter(lambda st: st[key] == status, self.cfg.status),
            None,
        )

    def _is_status_equal(self, jira_status, v1_status):
        jira_mapped_status = self._get_config_status_by(jira_status, "key")
        v1_mapped_status = self._get_config_status_by(v1_status, "inv_st")
        return jira_mapped_status["key"] == v1_mapped_status["key"]

    def _map_body(self, alert, notes=None):
        body = self._fields_to_body(alert, self.cfg.fields)
        body["project"] = {"id": self.project["id"]}
        body["issuetype"] = {"id": self.issue_type["id"]}
        body["summary"] = _format_summary(self.cfg.summary_prefix, alert)
        body["description"] = _format_description(alert, notes)
        log.debug("Mapped JIRA fields to body: %s", body)
        return body

    def _fields_to_body(self, alert, fields):
        copy = fields.copy()
        _map_v1_fields_value(alert, copy)
        return {
            field.get("key"): (
                [self._field_to_body(field, val) for val in field.get("value")]
                if isinstance(field.get("value"), list)
                else self._field_to_body(field, field.get("value"))
            )
            for field in copy
        }


    def _field_to_body(self, field, value):
        schema = field["schema"]
        field_type = schema["items"] if schema["type"] == "array" else schema["type"]
        if field_type == "string":
            return str(value)
        if field_type == "number":
            return int(value)
        if field_type == "user":
            return {"accountId": self._jira_user_acc_name(field.get("key"), value)}
        if isinstance(value, int) or str(value).isdigit():
            return {"id": str(value)}
        return {("name" if schema.get("system") else "value"): value}


    def run(self):
        while True:
            alert_list = self.v1_fetch_alerts()
            for alert in alert_list:
                _THREAD_LOCAL.id = alert.id
                if alert.id in self.cache:
                    try:
                        self._update_issue(alert)
                    except (RuntimeError, ValueError):
                        log.exception(
                            "Skip record, JIRA update failed, issue: %s",
                            self.cache[alert.id],
                        )
                else:
                    self._create_issue(alert)
                log.debug("Finished processing issue: %s", self.cache[alert.id])
            _THREAD_LOCAL.id = "App"
            log.info("Processed total: %s", len(alert_list))
            time.sleep(self.cfg.poll_time)

    def _create_issue(self, alert):
        self._jira_create_issue(alert)
        self._jira_add_attachment(alert)
        self._v1_add_note(alert)

    def _update_issue(self, alert):
        log.debug("Found in cache, checking if update required")
        jira_status = self._jira_status(alert)
        v1_status = alert.investigation_status
        self._validate_curr_statuses(jira_status, v1_status)
        if self._is_status_equal(jira_status, v1_status):
            log.debug(
                "Skipping update, status equal. JIRA %s, Vision One: %s",
                jira_status,
                v1_status.value,
            )
            return
        log.info(
            "Update detected, status not equal. JIRA: %s, Vision One: %s",
            jira_status,
            v1_status.value,
        )
        last_jira_update = self._jira_last_updated_time(alert)
        last_v1_update = datetime.datetime.strptime(
            alert.updated_date_time, "%Y-%m-%dT%H:%M:%S%z"
        )
        if last_jira_update > last_v1_update:
            log.debug("JIRA updated after Vision One")
            self._v1_edit_status(
                alert, self._get_config_status_by(jira_status, "key")["inv_st"]
            )
            return
        log.debug("Vision One updated after JIRA")
        config_status = self._get_config_status_by(v1_status, "inv_st")
        transition = self._jira_transition(alert, config_status)
        json = {
            "transition": {"id": transition["id"]},
        }
        fields = config_status.get("fields", [])
        if fields:
            if next(filter(lambda fi: not fi.get("schema"), fields), None):
                _map_fields_metadata(fields, transition["fields"])
            json["fields"] = self._fields_to_body(alert, fields)
        self._jira_update_status(alert, config_status, json)

    def _jira_create_issue(self, alert):
        log.info("Creating JIRA issue")

        # 获取alert的notes
        notes = []
        try:
            response = self.v_client.note.consume(
                lambda note: (
                    notes.append(note.content)
                    if not note.content.startswith("JIRA Incident Created:")
                    and not note.content.startswith("JIRA Incident Updated:")
                    else None
                ),
                alert.id
            )
            if response.result_code != pytmv1.ResultCode.SUCCESS:
                log.warning("Could not fetch notes for alert %s: %s", alert.id, response.error)
                notes = []
        except Exception as e:
            log.warning("Error fetching notes for alert %s: %s", alert.id, str(e))
            notes = []

        log.debug("Fetched %r notes for alert %s", notes, alert.id)
        data = {"fields": self._map_body(alert, notes)}
        log.debug("data: %s", data)
        response = self._send(
            "POST",
            CREATE_ISSUE,
            json=data,
        )
        log.debug("Received response from JIRA: %s", response)
        if response.status_code != 201:
            log.error(
                "Could not create JIRA issue: %s",
                response.content,
            )
            raise RuntimeError
        self._save_cache(alert.id, response.json()["key"])
        log.info("JIRA issue created: %s", response.json()["key"])

    def _jira_update_status(self, alert, config_status, body):
        response = self._send(
            "POST",
            DO_TRANSITION.format(self.cache[alert.id]),
            json=body,
        )
        log.debug("Received response from JIRA: %s", response)
        if not response.status_code == 204:
            log.error(
                "Could not update JIRA issue status: %s",
                response.content,
            )
            raise RuntimeError
        log.info(
            "Updated JIRA issue: %s, status to: %s",
            self.cache[alert.id],
            config_status["key"],
        )

    def _jira_add_attachment(self, alert):
        response = self._send(
            "POST",
            ADD_ATTACHMENT.format(self.cache[alert.id]),
            headers={"X-Atlassian-Token": "no-check"},
            files={
                "file": (
                    "json.txt",
                    alert.model_dump_json(),
                    "text/plain",
                )
            },
        )
        log.debug("Received response from JIRA: %s", response)
        if response.status_code != 200:
            log.error(
                "Could not attach raw json data to issue %s: %s",
                self.cache[alert.id],
                response.content,
            )
            raise RuntimeError
        log.info("Attached json data to issue: %s", self.cache[alert.id])

    def _jira_last_updated_time(self, alert):
        log.debug("Get JIRA last updated time")
        response = self._send("GET", GET_LAST_UPDATED.format(self.cache[alert.id]))
        log.debug("Received response from JIRA: %s", response)
        if response.status_code != 200:
            log.error(
                "Could not fetch JIRA last updated time: %s",
                response.content,
            )
            raise RuntimeError
        return datetime.datetime.strptime(
            response.json()["fields"]["updated"], "%Y-%m-%dT%H:%M:%S.%f%z"
        ).astimezone(datetime.timezone.utc)

    def _jira_issue_type(self):
        log.debug("Fetching JIRA Issue types for project: %s", self.project)
        response = self._send("GET", GET_ISSUE_TYPES.format(self.project["id"]))
        if response.status_code != 200:
            log.error(
                "Could not fetch JIRA issue types, status: %s\nresponse: %s",
                response.status_code,
                response.content,
            )
            raise RuntimeError
        return _filter_jira_issue_type(response.json(), self.cfg.issue_type)

    def _jira_fields(self):
        log.debug("Fetching JIRA Fields meta for issue_type: %s", self.issue_type)
        response = self._send(
            "GET", GET_FIELDS_META.format(self.project["id"], self.issue_type["id"])
        )
        log.debug("Received response from JIRA: %s", response)
        if response.status_code != 200:
            log.error("Could not fetch JIRA Fields meta: %s", response.content)
        json = response.json()
        return json.get("fields", json.get("values"))

    def _jira_project(self):
        response = self._send("GET", GET_PROJECT.format(self.cfg.project))
        if response.status_code != 200:
            log.error(
                "Could not fetch Project ID or KEY: %s, status: %s\nresponse: %s",
                self.cfg.project,
                response.status_code,
                response.content,
            )
            raise RuntimeError
        json = response.json()
        return {"id": json["id"], "key": json["key"]}

    def _jira_status(self, alert):
        log.debug("Fetching current JIRA status for issue: %s", self.cache[alert.id])
        response = self._send("GET", GET_STATUS.format(self.cache[alert.id]))
        log.debug("Received response from JIRA: %s", response)
        if response.status_code != 200:
            log.error("Could not fetch JIRA issue status: %s", response.content)
            raise RuntimeError
        return response.json()["fields"]["status"]["name"]

    def _jira_statuses(self):
        log.debug("Fetching JIRA statuses")
        response = self._send("GET", GET_STATUSES.format(self.cfg.project))
        log.debug("Received response from JIRA: %s", response)
        if response.status_code != 200:
            log.error("Could not fetch JIRA statuses: %s", response.content)
            raise RuntimeError
        return _filter_jira_status(response.json(), self.issue_type["id"])

    def _jira_transition(self, alert, status):
        log.debug("Fetching JIRA transitions for issue: %s", self.cache[alert.id])
        response = self._send("GET", GET_TRANSITIONS.format(self.cache[alert.id]))
        log.debug("Received response from JIRA: %s", response)
        if response.status_code != 200:
            log.error("Could not fetch JIRA issue transitions: %s", response.content)
            raise RuntimeError
        return _filter_jira_transition(response.json()["transitions"], status)

    def _jira_user_acc_name(self, field, value):
        # 移除使用 "username" 查询参数的 JIRA 用户搜索 API 调用
        # 这是为了适应 JIRA Cloud 的 GDPR 严格模式
        log.debug(
            "Directly using JIRA user ID from config for field: %s, value: %s", field, value
        )
        return value


    def _v1_add_note(self, alert):
        log.debug("Adding Vision One alert note")
        response = self.v_client.note.create(
            alert.id,
            f"JIRA Incident Created: {self.cache[alert.id]}\n"
            f"URL: {self.cfg.jira['url'] + '/browse/' + self.cache[alert.id]}",
        )
        log.debug("Received response from Vision One: %s", response)
        if ResultCode.SUCCESS != response.result_code:
            log.error("Could not create Vision One note: %s", response.error)
            raise RuntimeError
        log.info("Created Vision One note: %s", response.response.note_id)

    def _v1_edit_status(self, alert, status):
        log.debug("Editing Vision One alert status")
        response = self.v_client.alert.update_status(
            alert.id,
            status,
            self._v1_etag(alert),
        )
        log.debug("Received response from Vision One: %s", response)
        if ResultCode.SUCCESS != response.result_code:
            log.error(
                "Could not update Vision One Alert (%s) status: %s",
                self.cache[alert.id],
                response.error,
            )
            raise RuntimeError
        log.info(
            "Updated Vision One Alert (%s) status to: %s",
            self.cache[alert.id],
            status.value,
        )

    def _v1_etag(self, alert):
        log.debug("Fetching ETag from Vision One")
        response = self.v_client.alert.get(alert.id)
        log.debug("Received response from Vision One: %s", response)
        if ResultCode.SUCCESS != response.result_code:
            log.error(
                "Could not fetch ETag from Vision One (%s): %s",
                self.cache[alert.id],
                response.error,
            )
            raise RuntimeError
        return response.response.etag

    def v1_fetch_alerts(self):
        alert_list = []
        log.info(
            "Fetching alerts from Vision One [start_time: %s, end_time: %s, skip_closed: %s]",
            self.start_time,
            self.end_time,
            self.cfg.skip_closed,
        )
        result = self.v_client.alert.consume(
            lambda al: (
                alert_list.append(al)
                if al.id in self.cache
                or not self.cfg.skip_closed
                or al.investigation_status != InvestigationStatus.CLOSED
                else None
            ),
            self.start_time,
            self.end_time,
        )
        if ResultCode.SUCCESS != result.result_code:
            log.error("Could not fetch alerts from Vision One: %s", result.error)
            raise RuntimeError
        log.debug("Fetched alerts from Vision One: %s", alert_list)
        return alert_list

    def v1_fetch_alerts_notes(self, alert):
        log.info("Fetching notes from Vision One for alert: %s", alert.id)
        notes = []
        response = self.v_client.note.consume(
            lambda note: (
                notes.append(note.content)
                if not note.content.startswith("JIRA Incident Created:")
                and not note.content.startswith("JIRA Incident Updated:")
                else None

            ),
            alert.id)
        log.info("Received response from Vision One: %r", notes)
        if ResultCode.SUCCESS != response.result_code:
            log.error(
                "Could not fetch notes from Vision One (%s): %s",
                alert.id,
                response.error,
            )
            raise RuntimeError
        return response.response



def _map_fields_metadata(fields, jira_fields):
    possible_values = []
    for jira_field in jira_fields:
        field = _get_conf_field_by_name(fields, jira_field)
        if field:
            field["schema"] = jira_field["schema"]
            field["key"] = jira_field.get("key", jira_field["fieldId"])
            value = field["value"]
            if field["schema"]["type"] == "array" and not isinstance(value, list):
                field["value"] = [value]
        else:
            possible_values.append(
                (
                    jira_field.get("key", jira_field["fieldId"]),
                    jira_field["name"],
                    jira_field["required"],
                )
            )
    _validate_fields(fields, possible_values)


def _validate_fields(config_fields, possible_values):
    exclude = ["project", "issuetype", "summary", "description"]
    not_found = list(
        map(
            lambda field: field["name"],
            filter(
                lambda field: not field.get("schema"),
                config_fields,
            ),
        )
    )
    required_missing = list(
        map(
            lambda field: (field[0], field[1]),
            filter(lambda field: field[2] and field[0] not in exclude, possible_values),
        )
    )
    if not_found or required_missing:
        log.error(
            "Field mapping error\nConfig fields not found: %s\nRequired fields missing: %s\nValid fields: %s",
            not_found,
            required_missing,
            possible_values,
        )
        raise ValueError


def _map_statuses_metadata(statuses, jira_statuses):
    for status in statuses:
        matched_status = next(
            filter(
                lambda jst: jst[1].lower() == status["name"].lower(),
                jira_statuses,
            ),
            None,
        )
        investigation_status = _get_investigation_status(status["inv"])
        if matched_status:
            status["id"] = matched_status[0]
            status["key"] = matched_status[1]
        if investigation_status:
            status["inv_st"] = investigation_status
    _validate_statuses(statuses, jira_statuses)


def _validate_statuses(statuses, jira_statuses):
    status_not_found = list(filter(lambda status: not status.get("id"), statuses))
    inv_status_not_found = list(
        filter(lambda status: not status.get("inv_st"), statuses)
    )
    if status_not_found or inv_status_not_found:
        if status_not_found:
            log.error(
                "JIRA Status mapping error\nJIRA Status not found: %s\nValid names: %s",
                [st["name"] for st in status_not_found],
                [jst[1] for jst in jira_statuses],
            )
        if inv_status_not_found:
            log.error(
                "Vision One Status mapping error\nVision One Status not found: %s\nValid values: %s",
                [st["inv"] for st in inv_status_not_found],
                [inv.value for inv in InvestigationStatus],
            )
        raise ValueError


def _get_conf_field_by_name(config_fields, jira_field):
    return next(
        filter(
            lambda fi: str(fi["name"]).lower()
            in (
                jira_field.get("key", jira_field["fieldId"]),
                jira_field["name"].lower(),
            ),
            config_fields,
        ),
        None,
    )


def _get_investigation_status(value):
    return next(
        filter(
            lambda inv: inv.lower() == value.lower(),
            InvestigationStatus,
        ),
        None,
    )


def _map_v1_fields_value(alert, fields):
    v1_attr_fields = list(filter(lambda fi: _is_field_value_v1_attr(fi), fields))
    for field in v1_attr_fields:
        field["value"] = _get_v1_value(alert, field)


def _is_field_value_v1_attr(field):
    value = field.get("value")
    return next(
        filter(
            lambda val: str(val).startswith("alert."),
            value if isinstance(value, list) else [value],
        ),
        False,
    )


def _get_v1_value(alert, field):
    value = field.get("value")
    if isinstance(value, list):
        return [
            _parse_v1_value(alert, field.get("mapping"), field.get("key"), val)
            for val in value
        ]
    return _parse_v1_value(alert, field.get("mapping"), field.get("key"), value)


def _parse_v1_value(alert, mapping, key, value):
    attr = str(value)[6:]
    raw_v1_value = getattr(alert, attr, None)
    if not raw_v1_value:
        log.error(
            "Vision One mapped attribute not found\nValue: %s\nAttribute: %s",
            value,
            attr,
        )
        raise RuntimeError
    v1_value = raw_v1_value.value if isinstance(raw_v1_value, Enum) else raw_v1_value
    if mapping:
        value = next(
            map(
                lambda val: val[0],
                filter(
                    lambda item: item[1] == v1_value,
                    mapping.items(),
                ),
            ),
            None,
        )
        if not value:
            log.error(
                "JIRA value mapping error\nVision One value not found: %s\n"
                "Mapped values: %s\nField: '%s'",
                v1_value,
                {*mapping.values()},
                key,
            )
            raise ValueError
        v1_value = value
    return v1_value


def _filter_jira_issue_type(issue_types, value):
    issue_types = [
        {"id": it["id"], "name": it["name"]}
        for it in issue_types.get("issueTypes", issue_types.get("values"))
    ]
    issue_type = next(
        filter(
            lambda it: value in it.values(),
            issue_types,
        ),
        None,
    )
    if not issue_type:
        log.error(
            "Issue type verification error\nIssue type not found: %s\nPossible values: %s",
            value,
            issue_types,
        )
        raise ValueError
    return issue_type


def _filter_jira_status(issue_type_statuses, issue_type_id):
    jira_statuses = list(
        map(
            lambda status: (status["id"], status["name"]),
            next(filter(
                    lambda issue_type_status: issue_type_id
                    == issue_type_status["id"],
                    issue_type_statuses,
                ),
            )["statuses"],
        )
    )
    log.debug(
        "Filtered JIRA statuses: %s, for issue type id: %s",
        jira_statuses,
        issue_type_id,
    )
    return jira_statuses


def _filter_jira_transition(transitions, status):
    jira_transition = next(
        filter(lambda ts: ts["to"]["id"] == status["id"], transitions), None
    )
    if not jira_transition:
        log.error(
            "JIRA Status verification failed, status not found: %s\nPossible values: %s",
            status["key"],
            transitions,
        )
        raise ValueError
    return jira_transition


def _format_config_time(alert_time):
    if alert_time:
        formatted_time = (
            alert_time.strftime(ALERT_DATE_FORMAT)
            if isinstance(alert_time, datetime.datetime)
            else None
        )
        if not formatted_time:
            log.error(
                "Could not parse config start_time/end_time\nValue: %s\n"
                "Expected UTC date, example: 1970-12-25 18:00:00",
                alert_time,
            )
            raise ValueError
        return formatted_time
    return None


def _format_description(alert, notes=None):
    if hasattr(alert, "matched_rules"):
        rules = "\n** ".join(rule.name for rule in alert.matched_rules)
    else:
        rules = "\n** ".join(p.pattern for p in alert.matched_indicator_patterns)
    entities = "\n** ".join(
        entity.entity_type
        + ": "
        + (
            entity.entity_value
            if isinstance(entity.entity_value, str)
            else entity.entity_value.name
            + " ("
            + entity.entity_value.guid
            + ") - "
            + ",".join(entity.entity_value.ips)
        )
        for entity in alert.impact_scope.entities
    )
    indicators = "\n** ".join(
        indicator.type
        + ": "
        + (
            indicator.value
            if isinstance(indicator.value, str)
            else indicator.value.name
            + " ("
            + indicator.value.guid
            + ") - "
            + ",".join(indicator.value.ips)
        )
        for indicator in alert.indicators
    )
    mitres = []
    if hasattr(alert, "matched_rules"):
        for rule in alert.matched_rules:
            for matched_filter in rule.matched_filters:
                for tech in matched_filter.mitre_technique_ids:
                    mitres.append(tech)
    mitres = "\n** ".join(mitres)
    
    # 格式化notes部分
    notes_section = ""
    if notes:
        formatted_notes = "\n** ".join(notes)
        #notes_section = f"*Alert Notes:\n** {formatted_notes}"
    
        return (
            f"*Summary*\n\n* Detected by: XDR\n* Severity: {alert.severity}\n* Score: {alert.score}\n\n\n"
            f"*Event Details*\n\n* Vision One Model: {alert.model}\n* Rules\n** {rules}\n"
            f"* Vision One Alert Highlights:\n** {entities}\n"
            f"* Vision One Alert Indicators\n** {indicators}\n"
            f"* MITRE ATT&CK:\n** {mitres}\n"
            f"* Vision One Alert Link:\n** {alert.workbench_link}\n"
            f"* Alert Notes:\n** {formatted_notes}"
        )
    else:
        return (
            f"*Summary*\n\n* Detected by: XDR\n* Severity: {alert.severity}\n* Score: {alert.score}\n\n\n"
            f"*Event Details*\n\n* Vision One Model: {alert.model}\n* Rules\n** {rules}\n"
            f"* Vision One Alert Highlights:\n** {entities}\n"
            f"* Vision One Alert Indicators\n** {indicators}\n"
            f"* MITRE ATT&CK:\n** {mitres}\n"
            f"* Vision One Alert Link:\n** {alert.workbench_link}"
        )


def _format_summary(prefix, alert):
    host_entities = _format_host_entities(alert)
    if len(host_entities) > 0:
        value = host_entities[0].entity_value.name
    else:
        value = "Container/Cloud"
    return (
        (prefix + " | " if prefix else "")
        + alert.id
        + " | "
        + alert.model
        + " | "
        + ("Multiple Hosts" if len(host_entities) > 1 else value)
    )


def _format_host_entities(alert):
    return list(
        filter(
            lambda ent: ent.entity_type == EntityType.HOST,
            alert.impact_scope.entities,
        )
    )


if __name__ == "__main__":
    app = App()
    app.run()
