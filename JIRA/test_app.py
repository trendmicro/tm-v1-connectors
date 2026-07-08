"""Regression tests for the Vision One JIRA connector status sync.

Run from the JIRA/ directory so ``app.py`` can load ``config.yml`` at import:

    cd JIRA && python3 -m pytest test_app.py
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pytmv1 import AlertStatus, InvestigationResult, ResultCode, Severity

import app


def test_get_alert_status_accepts_current_and_legacy_values():
    assert app._get_alert_status("Open") == AlertStatus.OPEN
    assert app._get_alert_status("In Progress") == AlertStatus.IN_PROGRESS
    assert app._get_alert_status("Closed") == AlertStatus.CLOSED
    # Legacy "New" must alias to Open so pre-breakage configs keep working.
    assert app._get_alert_status("New") == AlertStatus.OPEN
    assert app._get_alert_status("new") == AlertStatus.OPEN
    assert app._get_alert_status("Bogus") is None


def test_get_investigation_result():
    assert app._get_investigation_result("True Positive") == InvestigationResult.TRUE_POSITIVE
    assert app._get_investigation_result("benign true positive") == (
        InvestigationResult.BENIGN_TRUE_POSITIVE
    )
    assert app._get_investigation_result("Nope") is None


def test_resolve_inv_result_prefers_explicit_key():
    cfg = {"inv_st": AlertStatus.CLOSED, "inv_result": "False Positive"}
    assert app._resolve_inv_result(cfg, AlertStatus.CLOSED) == InvestigationResult.FALSE_POSITIVE


def test_resolve_inv_result_falls_back_to_fields():
    cfg = {
        "inv_st": AlertStatus.CLOSED,
        "fields": [{"name": "investigationResult", "value": "True Positive"}],
    }
    assert app._resolve_inv_result(cfg, AlertStatus.CLOSED) == InvestigationResult.TRUE_POSITIVE


def test_resolve_inv_result_missing_on_close_raises():
    with pytest.raises(ValueError):
        app._resolve_inv_result({"inv_st": AlertStatus.CLOSED}, AlertStatus.CLOSED)


def test_resolve_inv_result_none_when_not_closing():
    assert app._resolve_inv_result({"inv_st": AlertStatus.OPEN}, AlertStatus.OPEN) is None


def test_v1_edit_status_sends_etag_and_status_in_correct_slots():
    """Guards the ETag/status arg-inversion bug.

    pytmv1 update_status signature is (alert_id, etag, status, inv_result,
    inv_status). The ETag must be the 2nd positional arg and the AlertStatus the
    ``status`` kwarg; the previous (alert_id, status, etag) order swapped them
    and produced Vision One error 3090003.
    """
    inst = app.App.__new__(app.App)
    inst.cache = {"WB-1": "SD-1"}
    inst.v_client = MagicMock()
    inst.v_client.alert.get.return_value = MagicMock(
        result_code=ResultCode.SUCCESS,
        response=MagicMock(etag="ETAG123"),
    )
    inst.v_client.alert.update_status.return_value = MagicMock(
        result_code=ResultCode.SUCCESS
    )
    alert = MagicMock(id="WB-1")

    inst._v1_edit_status(
        alert, {"inv_st": AlertStatus.CLOSED, "inv_result": "True Positive"}
    )

    args, kwargs = inst.v_client.alert.update_status.call_args
    assert args == ("WB-1", "ETAG123")
    assert kwargs["status"] == AlertStatus.CLOSED
    assert kwargs["inv_result"] == InvestigationResult.TRUE_POSITIVE


def _user_field_app(username):
    inst = app.App.__new__(app.App)
    inst.cfg = SimpleNamespace(jira={"username": username, "token": "t", "url": "u"})
    return inst


def test_field_to_body_user_onprem_uses_name():
    """On-premise (empty username -> Bearer auth) must send user by 'name'.

    JIRA Server/DC rejects the Cloud-only 'accountId' key for user fields.
    """
    inst = _user_field_app("")
    field = {"schema": {"type": "user"}, "key": "reporter"}
    assert inst._field_to_body(field, "b.kozdruj") == {"name": "b.kozdruj"}


def test_field_to_body_user_cloud_uses_accountid():
    inst = _user_field_app("me@example.com")
    field = {"schema": {"type": "user"}, "key": "reporter"}
    assert inst._field_to_body(field, "5b10ac8d82e05b22cc7d4ef5") == {
        "accountId": "5b10ac8d82e05b22cc7d4ef5"
    }


def test_fields_to_body_does_not_leak_across_alerts():
    """Regression: a shallow copy let alert N's resolved values persist to N+1.

    Resolving the shared `value: alert.id` must not mutate the config, so each
    alert produces its own labels.
    """
    inst = app.App.__new__(app.App)
    cfg_fields = [
        {
            "name": "labels",
            "key": "labels",
            "schema": {"type": "array", "items": "string"},
            "value": ["alert.id"],
        }
    ]
    first = inst._fields_to_body(SimpleNamespace(id="WB-1"), cfg_fields)
    second = inst._fields_to_body(SimpleNamespace(id="WB-2"), cfg_fields)
    assert first == {"labels": ["WB-1"]}
    assert second == {"labels": ["WB-2"]}
    # Config left untouched for the next alert.
    assert cfg_fields[0]["value"] == ["alert.id"]


def test_enum_val_renders_api_value():
    assert app._enum_val(Severity.LOW) == "low"
    assert app._enum_val("plain") == "plain"


def test_format_ref_handles_string_and_hostinfo():
    assert app._format_ref("1.2.3.4") == "1.2.3.4"
    host = SimpleNamespace(name="srv-01", guid="g-1", ips=["10.0.0.1", "10.0.0.2"])
    assert app._format_ref(host) == "srv-01 (g-1) - 10.0.0.1,10.0.0.2"
    # Empty guid/ips are omitted (no trailing "()").
    bare = SimpleNamespace(name="srv-02", guid="", ips=[])
    assert app._format_ref(bare) == "srv-02"


def test_dedupe_cap_dedupes_and_caps():
    assert app._dedupe_cap(["a", "a", "b", "a"]) == ["a", "b"]
    capped = app._dedupe_cap([str(i) for i in range(app._MAX_DESC_ITEMS + 5)])
    assert len(capped) == app._MAX_DESC_ITEMS + 1
    assert "more omitted" in capped[-1]
