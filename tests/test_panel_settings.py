from __future__ import annotations

import sys
import types

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
    SUBSCRIPTION_MESSAGE_KEYS,
    PanelSettingsPayload,
    apply_panel_settings_fallback,
    overlay_subscription_messages,
)
from app.services import panel_settings as panel_svc  # noqa: E402
from app.utils.jwt import get_subscription_payload, get_subscription_secret_keys  # noqa: E402


def test_panel_fallback_hard_stub_defaults_false_and_keeps_saved_true():
    assert apply_panel_settings_fallback(None)["sub_device_limit_hard_mode"] is False
    assert apply_panel_settings_fallback({"sub_device_limit_hard_mode": True})["sub_device_limit_hard_mode"] is True
    assert "sub_device_limit_hard_mode" in PANEL_SETTING_KEYS


def test_panel_fallback_fills_defaults():
    assert apply_panel_settings_fallback(None) == DEFAULT_PANEL_SETTINGS
    assert apply_panel_settings_fallback({})["bs_monthly_limit"] == 0
    assert apply_panel_settings_fallback({"bs_monthly_limit": 10})["bs_monthly_limit"] == 10
    assert apply_panel_settings_fallback({"bs_monthly_limit": "nope"})["bs_monthly_limit"] == 0


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
            sub_client_note="panel note",
            sub_revoked_server_text=["one", "two"],
        )
        saved = panel_svc.save_panel_settings(db, payload)
        assert saved["sub_custom_headers"] == "routing-enable: 0"
        assert saved["bs_monthly_limit"] == 1024
        assert saved["sub_routing_happ"] == "happ://r"
        assert saved["sub_client_note"] == "panel note"
        assert saved["sub_revoked_server_text"] == ["one", "two"]
        assert panel_svc.get_bs_monthly_limit(db) == 1024
        assert panel_svc.get_bs_monthly_limit(None) == 0


def _legacy(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"secret_key": secret, "bot_username": username} for secret, username in pairs]


def test_legacy_keys_absent_uses_env(monkeypatch):
    monkeypatch.setitem(DEFAULT_PANEL_SETTINGS, LEGACY_SECRET_KEYS_SETTING, ["from-env"])
    assert apply_panel_settings_fallback(None)[LEGACY_SECRET_KEYS_SETTING] == _legacy(("from-env", ""))
    assert apply_panel_settings_fallback({})[LEGACY_SECRET_KEYS_SETTING] == _legacy(("from-env", ""))
    assert apply_panel_settings_fallback({LEGACY_SECRET_KEYS_SETTING: []})[LEGACY_SECRET_KEYS_SETTING] == []
    assert apply_panel_settings_fallback({LEGACY_SECRET_KEYS_SETTING: ["a", "a", " b "]})[
        LEGACY_SECRET_KEYS_SETTING
    ] == _legacy(("a", ""), ("b", ""))


def test_legacy_keys_payload_normalizes_comma_string_and_keeps_first_username():
    payload = PanelSettingsPayload.model_validate({"subscription_legacy_secret_keys": "one, two, one"})
    assert payload.subscription_legacy_secret_keys == _legacy(("one", ""), ("two", ""))
    mixed = PanelSettingsPayload.model_validate(
        {
            "subscription_legacy_secret_keys": [
                "plain",
                {"secret_key": " plain ", "bot_username": "@later"},
                {"secret_key": "fresh", "bot_username": " @bot "},
            ]
        }
    )
    assert mixed.subscription_legacy_secret_keys == _legacy(("plain", ""), ("fresh", "bot"))


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
        assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(("keep-me", ""), ("other", ""))
        assert panel_svc.get_legacy_subscription_secret_keys(db) == ["keep-me", "other"]

        omitted = PanelSettingsPayload(bs_monthly_limit=7)
        assert LEGACY_SECRET_KEYS_SETTING not in omitted.model_fields_set
        kept = panel_svc.save_panel_settings(db, omitted)
        assert kept[LEGACY_SECRET_KEYS_SETTING] == _legacy(("keep-me", ""), ("other", ""))
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


def test_add_legacy_key_preserves_other_settings_and_is_idempotent(monkeypatch):
    engine = _panel_db()
    cleared: list[bool] = []
    monkeypatch.setattr(panel_svc, "clear_legacy_subscription_secret_keys_cache", lambda: cleared.append(True))
    with Session(engine) as db:
        panel_svc.save_panel_settings(
            db,
            PanelSettingsPayload(bs_monthly_limit=7, subscription_legacy_secret_keys=["already-there"]),
        )
        panel_svc.add_legacy_subscription_secret_key(db, "external-panel-key")
        panel_svc.add_legacy_subscription_secret_key(db, "external-panel-key")

        saved = panel_svc.get_panel_settings(db)
        assert saved["bs_monthly_limit"] == 7
        assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(("already-there", ""), ("external-panel-key", ""))
    assert cleared == [True, True, True]


def test_add_legacy_key_keeps_env_keys_when_the_field_is_absent(monkeypatch):
    monkeypatch.setitem(DEFAULT_PANEL_SETTINGS, LEGACY_SECRET_KEYS_SETTING, ["from-env"])
    engine = _panel_db()
    with Session(engine) as db:
        db.add(GlobalSetting(key=PANEL_SETTINGS_KEY, data={"bs_monthly_limit": 3}))
        db.commit()
        panel_svc.add_legacy_subscription_secret_key(db, "new-key", "@bot")
        assert panel_svc.get_legacy_subscription_secret_keys(db) == ["from-env", "new-key"]
        assert panel_svc.get_panel_settings(db)["bs_monthly_limit"] == 3


def test_add_legacy_key_does_not_restore_env_when_the_saved_list_is_empty(monkeypatch):
    monkeypatch.setitem(DEFAULT_PANEL_SETTINGS, LEGACY_SECRET_KEYS_SETTING, ["from-env"])
    engine = _panel_db()
    with Session(engine) as db:
        panel_svc.save_panel_settings(db, PanelSettingsPayload(subscription_legacy_secret_keys=[]))
        panel_svc.add_legacy_subscription_secret_key(db, "new-key", "bot")
        assert panel_svc.get_legacy_subscription_secret_keys(db) == ["new-key"]


def test_stored_string_keys_are_read_with_empty_username():
    engine = _panel_db()
    with Session(engine) as db:
        db.add(GlobalSetting(key=PANEL_SETTINGS_KEY, data={LEGACY_SECRET_KEYS_SETTING: ["stored-plain"]}))
        db.commit()
        assert panel_svc.get_panel_settings(db)[LEGACY_SECRET_KEYS_SETTING] == _legacy(("stored-plain", ""))
        assert panel_svc.get_legacy_subscription_secret_keys(db) == ["stored-plain"]


def test_add_legacy_key_keeps_existing_username_empty_and_stores_a_new_one():
    engine = _panel_db()
    with Session(engine) as db:
        panel_svc.save_panel_settings(db, PanelSettingsPayload(subscription_legacy_secret_keys=["already-there"]))
        panel_svc.add_legacy_subscription_secret_key(db, "already-there", "later-bot")
        panel_svc.add_legacy_subscription_secret_key(db, "fresh-key", "@fresh-bot")

        saved = panel_svc.get_panel_settings(db)
        assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(("already-there", ""), ("fresh-key", "fresh-bot"))
        assert panel_svc.get_legacy_subscription_secret_keys(db) == ["already-there", "fresh-key"]


def test_save_after_legacy_add_keeps_key_when_payload_omits_legacy_field():
    """Оба пути берут одну row-lock, поэтому второй writer видит добавленный ключ."""
    engine = _panel_db()
    with Session(engine) as db:
        panel_svc.save_panel_settings(db, PanelSettingsPayload(bs_monthly_limit=7))
        panel_svc.add_legacy_subscription_secret_key(db, "external-panel-key")

        saved = panel_svc.save_panel_settings(db, PanelSettingsPayload(bs_monthly_limit=9))

    assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(("external-panel-key", ""))
    assert saved["bs_monthly_limit"] == 9


def test_stale_form_save_keeps_key_imported_in_another_session(monkeypatch):
    """Форма открыта, импорт в другой сессии, сохранение чужого поля не затирает ключ."""
    engine = _panel_db()
    with Session(engine) as setup:
        panel_svc.save_panel_settings(
            setup,
            PanelSettingsPayload(bs_monthly_limit=1, subscription_legacy_secret_keys=["loaded-key"]),
        )

    with Session(engine) as opened:
        baseline = panel_svc.get_panel_settings(opened)[LEGACY_SECRET_KEYS_SETTING]

    with Session(engine) as importer:
        panel_svc.add_legacy_subscription_secret_key(importer, "imported-key", "bot")

    with Session(engine) as saver:
        saved = panel_svc.save_panel_settings(
            saver,
            PanelSettingsPayload(
                bs_monthly_limit=9,
                subscription_legacy_secret_keys=baseline,
                subscription_legacy_secret_keys_baseline=baseline,
            ),
        )
        secrets = panel_svc.get_legacy_subscription_secret_keys(saver)
        stored = dict(saver.query(GlobalSetting).filter(GlobalSetting.key == PANEL_SETTINGS_KEY).one().data)

    assert saved["bs_monthly_limit"] == 9
    assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(("loaded-key", ""), ("imported-key", "bot"))
    assert secrets == ["loaded-key", "imported-key"]
    assert "subscription_legacy_secret_keys_baseline" not in stored

    monkeypatch.setattr("app.utils.jwt.get_secret_key", lambda: "primary-secret")
    monkeypatch.setattr(panel_svc, "get_cached_legacy_subscription_secret_keys", lambda: tuple(secrets))
    token = _signed_sub_token("user_1", 1000, "imported-key")
    payload = get_subscription_payload(token)
    assert payload is not None
    assert payload["username"] == "user_1"


def test_key_edits_keep_keys_added_since_the_form_loaded():
    """Удаление и username считаются от снимка загрузки, импортированный ключ остаётся."""
    engine = _panel_db()
    with Session(engine) as setup:
        panel_svc.save_panel_settings(
            setup,
            PanelSettingsPayload(
                subscription_legacy_secret_keys=[
                    {"secret_key": "keep", "bot_username": ""},
                    {"secret_key": "drop", "bot_username": "old"},
                ]
            ),
        )

    with Session(engine) as opened:
        baseline = panel_svc.get_panel_settings(opened)[LEGACY_SECRET_KEYS_SETTING]

    with Session(engine) as importer:
        panel_svc.add_legacy_subscription_secret_key(importer, "imported-key", "bot")

    with Session(engine) as saver:
        saved = panel_svc.save_panel_settings(
            saver,
            PanelSettingsPayload(
                subscription_legacy_secret_keys=[
                    {"secret_key": "keep", "bot_username": "renamed"},
                    {"secret_key": "typed", "bot_username": "@manual"},
                ],
                subscription_legacy_secret_keys_baseline=baseline,
            ),
        )

    assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(
        ("keep", "renamed"),
        ("typed", "manual"),
        ("imported-key", "bot"),
    )


def test_empty_baseline_keeps_key_imported_after_the_form_loaded():
    """Пустой снимок — валидное «ключей не было», а не сигнал заменить список."""
    engine = _panel_db()
    with Session(engine) as setup:
        panel_svc.save_panel_settings(setup, PanelSettingsPayload(subscription_legacy_secret_keys=[]))

    with Session(engine) as opened:
        baseline = panel_svc.get_panel_settings(opened)[LEGACY_SECRET_KEYS_SETTING]
        assert baseline == []

    with Session(engine) as importer:
        panel_svc.add_legacy_subscription_secret_key(importer, "imported-key", "bot")

    with Session(engine) as saver:
        saved = panel_svc.save_panel_settings(
            saver,
            PanelSettingsPayload(
                bs_monthly_limit=4,
                subscription_legacy_secret_keys=baseline,
                subscription_legacy_secret_keys_baseline=baseline,
            ),
        )

    assert saved["bs_monthly_limit"] == 4
    assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(("imported-key", "bot"))


def test_add_legacy_key_creates_settings_row_and_keeps_env_key(monkeypatch):
    monkeypatch.setitem(DEFAULT_PANEL_SETTINGS, LEGACY_SECRET_KEYS_SETTING, ["from-env"])
    engine = _panel_db()
    with Session(engine) as db:
        assert db.query(GlobalSetting).filter(GlobalSetting.key == PANEL_SETTINGS_KEY).first() is None
        panel_svc.add_legacy_subscription_secret_key(db, "new-key", "@bot")
        saved = panel_svc.get_panel_settings(db)
        assert saved["bs_monthly_limit"] == 0
        assert saved[LEGACY_SECRET_KEYS_SETTING] == _legacy(("from-env", ""), ("new-key", "bot"))
        assert db.query(GlobalSetting).filter(GlobalSetting.key == PANEL_SETTINGS_KEY).count() == 1


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


def test_panel_payload_includes_subscription_message_keys():
    for key in SUBSCRIPTION_MESSAGE_KEYS:
        assert key in PanelSettingsPayload.model_fields
        assert key in PANEL_SETTING_KEYS
        assert key in DEFAULT_PANEL_SETTINGS


def test_panel_fallback_empty_announce_uses_factory_default():
    resolved = apply_panel_settings_fallback({"sub_client_note": "  ", "sub_bs_limit_server_text": []})
    assert resolved["sub_client_note"] == DEFAULT_PANEL_SETTINGS["sub_client_note"]
    assert resolved["sub_bs_limit_server_text"] == []


def test_overlay_subscription_messages_prefers_panel_texts():
    bot = {"sub_profile_title": "Keep me", "sub_client_note": "from-bot", "sub_device_limit_hard_mode": True}
    panel = {
        "sub_client_note": "from-panel",
        "sub_revoked_server_text": ["one", " two "],
        "sub_bs_limit_server_text": [],
    }
    merged = overlay_subscription_messages(bot, panel)
    assert merged["sub_profile_title"] == "Keep me"
    assert merged["sub_device_limit_hard_mode"] is True
    assert merged["sub_client_note"] == "from-panel"
    assert merged["sub_revoked_server_text"] == ["one", "two"]
    assert merged["sub_bs_limit_server_text"] == []
    assert merged["sub_expired_announce_text"] == DEFAULT_PANEL_SETTINGS["sub_expired_announce_text"]


def test_overlay_empty_announce_falls_back_to_factory():
    merged = overlay_subscription_messages({}, {"sub_client_note": ""})
    assert merged["sub_client_note"] == DEFAULT_PANEL_SETTINGS["sub_client_note"]
