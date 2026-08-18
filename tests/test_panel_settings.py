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
from app.db.models import GlobalSetting  # noqa: E402
from app.models.bot import BotSettingsPayload, apply_bot_settings_fallback  # noqa: E402
from app.models.settings import (  # noqa: E402
    DEFAULT_PANEL_SETTINGS,
    PANEL_SETTING_KEYS,
    PANEL_SETTINGS_KEY,
    PanelSettingsPayload,
    apply_panel_settings_fallback,
)
from app.services import panel_settings as panel_svc  # noqa: E402


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
