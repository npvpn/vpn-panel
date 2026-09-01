from __future__ import annotations

import sys
import types

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db.base import Base  # noqa: E402
from app.db.models import JWT, GlobalSetting  # noqa: E402
from app.models.bot import BotSettingsPayload, apply_bot_settings_fallback  # noqa: E402
from app.models.settings import (  # noqa: E402
    DEFAULT_PANEL_SETTINGS,
    LEGACY_SECRET_KEYS_SETTING,
    PANEL_SETTING_KEYS,
    PANEL_SETTINGS_KEY,
    PanelSettingsPayload,
    apply_panel_settings_fallback,
)
from app.services import panel_settings as panel_svc  # noqa: E402
from app.utils.jwt import get_subscription_payload, get_subscription_secret_keys  # noqa: E402


def test_panel_fallback_fills_defaults():
    assert apply_panel_settings_fallback(None) == DEFAULT_PANEL_SETTINGS
    assert apply_panel_settings_fallback({})["bs_monthly_limit"] == 0
    assert apply_panel_settings_fallback({"bs_monthly_limit": 10})["bs_monthly_limit"] == 10
    assert apply_panel_settings_fallback({"bs_monthly_limit": "nope"})["bs_monthly_limit"] == 0


def test_panel_payload_accepts_empty_json_and_rejects_invalid():
    PanelSettingsPayload.model_validate({"sub_v2ray_json_template": ""})
    PanelSettingsPayload.model_validate({"sub_v2ray_json_template": '{"dns": {}}'})
    with pytest.raises(ValidationError):
        PanelSettingsPayload.model_validate({"sub_v2ray_json_template": "["})
    with pytest.raises(ValidationError):
        PanelSettingsPayload.model_validate({"sub_routing_json_default": "[]"})


def test_bot_fallback_ignores_legacy_panel_keys():
    resolved = apply_bot_settings_fallback(
        {
            "show_ads": False,
            "bs_monthly_limit": 123,
            "sub_custom_headers": "X-A: 1",
            "sub_routing_happ": "happ://x",
        }
    )
    assert resolved["show_ads"] is False
    for key in PANEL_SETTING_KEYS:
        assert key not in resolved


def test_bot_settings_payload_does_not_include_panel_fields():
    for key in PANEL_SETTING_KEYS:
        assert key not in BotSettingsPayload.model_fields


def test_panel_settings_service_roundtrip():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GlobalSetting.__table__])
    with Session(engine) as db:
        empty = panel_svc.get_panel_settings(db)
        assert empty["bs_monthly_limit"] == 0
        assert db.query(GlobalSetting).filter(GlobalSetting.key == PANEL_SETTINGS_KEY).first() is None

        payload = PanelSettingsPayload(
            sub_custom_headers="routing-enable: 0",
            bs_monthly_limit=1024,
            sub_routing_happ="happ://r",
        )
        saved = panel_svc.save_panel_settings(db, payload)
        assert saved["sub_custom_headers"] == "routing-enable: 0"
        assert saved["bs_monthly_limit"] == 1024
        assert saved["sub_routing_happ"] == "happ://r"
        assert panel_svc.get_bs_monthly_limit(db) == 1024
        assert panel_svc.get_bs_monthly_limit(None) == 0


def test_legacy_keys_absent_uses_env(monkeypatch):
    monkeypatch.setitem(DEFAULT_PANEL_SETTINGS, LEGACY_SECRET_KEYS_SETTING, ["from-env"])
    assert apply_panel_settings_fallback(None)[LEGACY_SECRET_KEYS_SETTING] == ["from-env"]
    assert apply_panel_settings_fallback({})[LEGACY_SECRET_KEYS_SETTING] == ["from-env"]
    assert apply_panel_settings_fallback({LEGACY_SECRET_KEYS_SETTING: []})[LEGACY_SECRET_KEYS_SETTING] == []
    assert apply_panel_settings_fallback({LEGACY_SECRET_KEYS_SETTING: ["a", "a", " b "]})[
        LEGACY_SECRET_KEYS_SETTING
    ] == ["a", "b"]


def test_legacy_keys_payload_normalizes_comma_string():
    payload = PanelSettingsPayload.model_validate({"subscription_legacy_secret_keys": "one, two, one"})
    assert payload.subscription_legacy_secret_keys == ["one", "two"]


def _panel_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[GlobalSetting.__table__, JWT.__table__])
    return engine


def test_save_legacy_keys_and_omitted_field_keeps_existing():
    engine = _panel_db()
    with Session(engine) as db:
        saved = panel_svc.save_panel_settings(
            db, PanelSettingsPayload(subscription_legacy_secret_keys=["keep-me", "keep-me", " other "])
        )
        assert saved[LEGACY_SECRET_KEYS_SETTING] == ["keep-me", "other"]
        assert panel_svc.get_legacy_subscription_secret_keys(db) == ["keep-me", "other"]

        omitted = PanelSettingsPayload(bs_monthly_limit=7)
        assert LEGACY_SECRET_KEYS_SETTING not in omitted.model_fields_set
        kept = panel_svc.save_panel_settings(db, omitted)
        assert kept[LEGACY_SECRET_KEYS_SETTING] == ["keep-me", "other"]
        assert kept["bs_monthly_limit"] == 7

        emptied = panel_svc.save_panel_settings(db, PanelSettingsPayload(subscription_legacy_secret_keys=[]))
        assert emptied[LEGACY_SECRET_KEYS_SETTING] == []


def test_save_clears_legacy_key_cache(monkeypatch):
    engine = _panel_db()
    cleared: list[bool] = []
    monkeypatch.setattr(panel_svc, "clear_legacy_subscription_secret_keys_cache", lambda: cleared.append(True))
    with Session(engine) as db:
        panel_svc.save_panel_settings(db, PanelSettingsPayload(subscription_legacy_secret_keys=["a"]))
    assert cleared == [True]


def test_with_primary_jwt_secret_reads_jwt_table():
    engine = _panel_db()
    with Session(engine) as db:
        db.add(JWT(secret_key="primary-from-db"))
        db.commit()
        out = panel_svc.with_primary_jwt_secret(db, {"bs_monthly_limit": 0})
        assert out["primary_jwt_secret"] == "primary-from-db"
        assert panel_svc.get_primary_jwt_secret(db) == "primary-from-db"


def _signed_sub_token(username: str, created_at: int, secret: str) -> str:
    from base64 import b64encode
    from hashlib import sha256

    data = username + "," + str(created_at)
    data_b64 = b64encode(data.encode("utf-8"), altchars=b"-_").decode("utf-8").rstrip("=")
    sign = b64encode(sha256((data_b64 + secret).encode("utf-8")).digest(), altchars=b"-_").decode("utf-8")[:10]
    return data_b64 + sign


def test_subscription_payload_accepts_legacy_db_key(monkeypatch):
    monkeypatch.setattr("app.utils.jwt.get_secret_key", lambda: "primary-secret")
    monkeypatch.setattr(panel_svc, "get_cached_legacy_subscription_secret_keys", lambda: ("legacy-secret",))
    token = _signed_sub_token("8691193104_478", 1787734240, "legacy-secret")
    payload = get_subscription_payload(token)
    assert payload is not None
    assert payload["username"] == "8691193104_478"
    assert get_subscription_secret_keys() == ["primary-secret", "legacy-secret"]


def test_subscription_payload_rejects_unknown_legacy_key(monkeypatch):
    monkeypatch.setattr("app.utils.jwt.get_secret_key", lambda: "primary-secret")
    monkeypatch.setattr(panel_svc, "get_cached_legacy_subscription_secret_keys", lambda: ())
    token = _signed_sub_token("user_1", 1000, "unknown-secret")
    assert get_subscription_payload(token) is None
