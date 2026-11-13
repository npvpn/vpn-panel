"""V2Ray-заглушки подписки для revoked/expired/unsupported/device_limit.

Выбор текста — без тяжёлых зависимостей; сборка payload лениво импортирует v2ray.
"""

from __future__ import annotations

import base64
import urllib.parse as urlparse
from collections.abc import Mapping, Sequence
from typing import Literal

ZERO_STUB_ID = "00000000-0000-0000-0000-000000000000"
INCY_STUB_ID = "11111111-1111-4111-8111-111111111111"
INCY_STUB_ADDRESS = "198.18.0.1"
INCY_STUB_PORT = 443
JSON_STUB_ID = "11111111-1111-4111-8111-111111111111"
JSON_STUB_ADDRESS = "198.18.0.1"
JSON_STUB_PORT = 443


def add_information_placeholder(conf, remark: str) -> None:
    """Информационный хост: валидный профиль с заведомо нерабочим endpoint.

    Тип протокола выбирается по возможностям формата подписки, а не по
    реальному инбаунду хоста. Для JSON используем тот же VLESS-профиль,
    что и у уже существующих заглушек статуса подписки.
    """
    from app.subscription.clash import ClashConfiguration, ClashMetaConfiguration
    from app.subscription.outline import OutlineConfiguration

    protocol = "vless"
    settings = {"id": JSON_STUB_ID, "flow": ""}
    if isinstance(conf, OutlineConfiguration):
        protocol = "shadowsocks"
        settings = {"password": "disabled-placeholder", "method": "aes-256-gcm"}
    elif isinstance(conf, ClashConfiguration) and not isinstance(conf, ClashMetaConfiguration):
        protocol = "vmess"

    inbound = {
        "network": "ws",
        "protocol": protocol,
        "port": JSON_STUB_PORT,
        "tls": "none",
        "header_type": "",
        "fragment_setting": "",
        "noise_setting": "",
        "path": "",
        "host": "",
        "sni": "",
    }
    conf.add(remark=remark, address=JSON_STUB_ADDRESS, inbound=inbound, settings=settings)


def _vless_stub_link(
    remark: str,
    *,
    id: str = ZERO_STUB_ID,
    address: str = "0.0.0.0",
    port: int = 0,
) -> str:
    """Минимальная vless-ссылка заглушки (0.0.0.0:0), без импорта v2ray.py."""
    payload = {
        "security": "none",
        "type": "ws",
        "headerType": "",
        "path": "",
        "host": "",
    }
    return "vless://" + f"{id}@{address}:{port}?" + urlparse.urlencode(payload) + f"#{urlparse.quote(remark)}"


def pick_status_stub_text_list(
    *,
    revoked: bool,
    expired: bool,
    device_limited_hard: bool,
    unsupported_client: bool,
    settings: Mapping[str, Sequence[str]],
) -> list[str]:
    """Приоритет статусов как в generate_subscription."""
    if revoked:
        return list(settings["sub_revoked_server_text"])
    if expired:
        return list(settings["sub_expired_server_text"])
    if device_limited_hard:
        return list(settings["sub_device_limit_server_text"])
    if unsupported_client:
        return list(settings["sub_unsupported_client_server_text"])
    return []


def build_v2ray_status_stub(
    text_list: Sequence[str],
    config_format: Literal["v2ray", "v2ray-json"],
    *,
    as_base64: bool,
    reverse: bool = False,
    v2ray_stub_profile: Literal["default", "incy"] = "default",
) -> str:
    """Мёртвые vless-узлы c remark из text_list (формат-зависимые параметры)."""
    if not text_list:
        if config_format == "v2ray":
            return base64.b64encode(b"").decode()
        config = "[]"
        if as_base64:
            config = base64.b64encode(config.encode()).decode()
        return config

    if config_format == "v2ray":
        if v2ray_stub_profile == "incy":
            payload = "\n".join(
                _vless_stub_link(
                    remark,
                    id=INCY_STUB_ID,
                    address=INCY_STUB_ADDRESS,
                    port=INCY_STUB_PORT,
                )
                for remark in text_list
            )
        else:
            payload = "\n".join(_vless_stub_link(remark) for remark in text_list)
        return base64.b64encode(payload.encode()).decode()

    from app.subscription.v2ray import V2rayJsonConfig

    stub_inbound = {
        "network": "ws",
        "protocol": "vless",
        "port": JSON_STUB_PORT,
        "tls": "none",
        "header_type": "",
        "fragment_setting": "",
        "noise_setting": "",
        "path": "",
        "host": "",
        "sni": "",
    }
    conf = V2rayJsonConfig()
    for remark in text_list:
        conf.add(
            remark=remark,
            address=JSON_STUB_ADDRESS,
            inbound=stub_inbound,
            settings={"id": JSON_STUB_ID},
        )
    config = conf.render(reverse=reverse)
    if as_base64:
        config = base64.b64encode(config.encode()).decode()
    return config
