from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    (
        "ua",
        "kwargs",
        "config_format",
        "media_type",
        "as_base64",
        "reverse",
    ),
    [
        (
            "Mozilla/5.0 Chrome/145.0.0.0; Clash.Meta; Mihomo; Shadowrocket;",
            {},
            "clash-meta",
            "text/yaml",
            False,
            False,
        ),
        ("Clash/1.0", {}, "clash", "text/yaml", False, False),
        ("SFA/1.0", {}, "sing-box", "application/json", False, False),
        ("Outline/1.0", {}, "outline", "application/json", False, False),
        (
            "v2rayN/6.40",
            {"use_custom_json_for_v2rayn": True},
            "v2ray-json",
            "application/json",
            False,
            False,
        ),
        (
            "v2rayN/6.39",
            {"use_custom_json_for_v2rayn": True},
            "v2ray",
            "text/plain",
            True,
            False,
        ),
        (
            "v2rayNG/1.8.29",
            {"use_custom_json_for_v2rayng": True},
            "v2ray-json",
            "application/json",
            False,
            False,
        ),
        (
            "v2rayNG/1.8.20",
            {"use_custom_json_for_v2rayng": True},
            "v2ray-json",
            "application/json",
            False,
            True,
        ),
        (
            "v2rayNG/1.8.17",
            {"use_custom_json_for_v2rayng": True},
            "v2ray",
            "text/plain",
            True,
            False,
        ),
        (
            "Streisand/1",
            {"use_custom_json_default": True},
            "v2ray-json",
            "application/json",
            False,
            False,
        ),
        ("Streisand/1", {}, "v2ray", "text/plain", True, False),
        (
            "Happ/1.63.1",
            {"use_custom_json_for_happ": True},
            "v2ray-json",
            "application/json",
            False,
            False,
        ),
        (
            "Happ/1.60.0",
            {"use_custom_json_for_happ": True},
            "v2ray",
            "text/plain",
            True,
            False,
        ),
        (
            "INCY/3.3.0",
            {"use_custom_json_default": True},
            "incy",
            "application/json",
            False,
            False,
        ),
        ("INCY/3.3.0", {}, "incy", "text/plain", False, False),
        ("curl/8.0", {}, "v2ray", "text/plain", True, False),
    ],
)
def test_resolve_plan_by_user_agent_all_clients(
    ua: str,
    kwargs: dict[str, bool],
    config_format: str,
    media_type: str,
    as_base64: bool,
    reverse: bool,
):
    try:
        from app.subscription.subscription_service import resolve_subscription_plan_by_user_agent
    except Exception as exc:
        pytest.skip(f"subscription_service deps unavailable: {exc}")

    default_flags = {
        "use_custom_json_default": False,
        "use_custom_json_for_v2rayn": False,
        "use_custom_json_for_v2rayng": False,
        "use_custom_json_for_streisand": False,
        "use_custom_json_for_happ": False,
    }
    default_flags.update(kwargs)
    plan = resolve_subscription_plan_by_user_agent(ua, **default_flags)

    assert plan.config_format == config_format
    assert plan.media_type == media_type
    assert plan.as_base64 is as_base64
    assert plan.reverse is reverse


def test_resolve_plan_by_client_type():
    try:
        from app.subscription.subscription_service import resolve_subscription_plan_by_client_type
    except Exception as exc:
        pytest.skip(f"subscription_service deps unavailable: {exc}")

    client_config = {
        "clash-meta": {"config_format": "clash-meta", "media_type": "text/yaml", "as_base64": False, "reverse": False},
        "clash": {"config_format": "clash", "media_type": "text/yaml", "as_base64": False, "reverse": False},
        "sing-box": {
            "config_format": "sing-box",
            "media_type": "application/json",
            "as_base64": False,
            "reverse": False,
        },
        "outline": {"config_format": "outline", "media_type": "application/json", "as_base64": False, "reverse": False},
        "v2ray": {"config_format": "v2ray", "media_type": "text/plain", "as_base64": True, "reverse": False},
        "v2ray-json": {
            "config_format": "v2ray-json",
            "media_type": "application/json",
            "as_base64": False,
            "reverse": False,
        },
        "incy": {"config_format": "incy", "media_type": "text/plain", "as_base64": False, "reverse": False},
    }

    incy_json = resolve_subscription_plan_by_client_type(
        "incy", client_config=client_config, use_custom_json_default=True
    )
    assert incy_json.media_type == "application/json"
    assert incy_json.config_format == "incy"

    incy_plain = resolve_subscription_plan_by_client_type(
        "incy", client_config=client_config, use_custom_json_default=False
    )
    assert incy_plain.media_type == "text/plain"

    clash_meta = resolve_subscription_plan_by_client_type(
        "clash-meta", client_config=client_config, use_custom_json_default=False
    )
    assert clash_meta.config_format == "clash-meta"
    assert clash_meta.media_type == "text/yaml"

    with pytest.raises(ValueError):
        resolve_subscription_plan_by_client_type("unknown", client_config=client_config, use_custom_json_default=False)


def _announce_settings(**overrides):
    settings = {
        "sub_client_note": "",
        "sub_revoked_announce_text": "",
        "sub_expired_announce_text": "",
        "sub_device_limit_announce_text": "",
        "sub_unsupported_client_announce_text": "",
        "sub_bs_limit_announce_text": "",
    }
    settings.update(overrides)
    return settings


def test_announce_uses_bs_limit_text_when_nodes_blocked():
    from app.subscription.bs_context import BsContext
    from app.subscription.subscription_service import resolve_announce_text

    bs = BsContext(blocked_node_ids=frozenset({7}), stub_text="лимит")
    text = resolve_announce_text(
        object(),
        is_revoked=False,
        is_expired=False,
        device_limited=False,
        unsupported_blocks=False,
        bs=bs,
        bot_settings=_announce_settings(sub_bs_limit_announce_text="БС-лимит исчерпан"),
        get_user_note=lambda _user, template: template,
    )
    assert text == "БС-лимит исчерпан"


def test_announce_ignores_bs_text_without_blocks():
    from app.subscription.bs_context import BsContext
    from app.subscription.subscription_service import resolve_announce_text

    text = resolve_announce_text(
        object(),
        is_revoked=False,
        is_expired=False,
        device_limited=False,
        unsupported_blocks=False,
        bs=BsContext.empty(),
        bot_settings=_announce_settings(
            sub_client_note="заметка",
            sub_bs_limit_announce_text="БС-лимит исчерпан",
        ),
        get_user_note=lambda _user, template: template,
    )
    assert text == "заметка"
