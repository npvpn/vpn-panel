from collections.abc import Sequence
from random import randint
from typing import TYPE_CHECKING

from app.models.proxy import ProxyHostSecurity
from app.utils.store import DictStorage
from app.utils.system import check_port
from app.xray import operations
from app.xray.config import XRayConfig
from app.xray.core import XRayCore
from app.xray.host_addresses import resolve_host_addresses, resolve_host_node_ids
from app.xray.inbound_filter import apply_inbound_filter
from app.xray.node import XRayNode
from config import XRAY_ASSETS_PATH, XRAY_EXECUTABLE_PATH, XRAY_JSON
from xray_api import XRay as XRayAPI
from xray_api import exceptions, types
from xray_api import exceptions as exc

core = XRayCore(XRAY_EXECUTABLE_PATH, XRAY_ASSETS_PATH)

# Search for a free API port
try:
    for api_port in range(randint(10000, 60000), 65536):
        if not check_port(api_port):
            break
finally:
    config = XRayConfig(XRAY_JSON, api_port=api_port)
    del api_port

api = XRayAPI(config.api_host, config.api_port)

nodes: dict[int, XRayNode] = {}

# Кеш тегов инбаундов Master (пусто ⇒ Master поднимает все инбаунды).
# Обновляется через operations.refresh_master_inbounds(db).
master_inbound_tags: list[str] = []

# list(...) — снимок на момент вызова: refresh_master_inbounds мутирует список
# in-place (master_inbound_tags[:] = ...), а хук может читаться из потока
# APScheduler (core_health_check) параллельно с PUT-обновлением.
core.inbound_filter = lambda cfg: apply_inbound_filter(cfg, list(master_inbound_tags))


if TYPE_CHECKING:
    from app.db.models import ProxyHost


@DictStorage
def hosts(storage: dict):
    from app.db import GetDB, crud

    storage.clear()
    with GetDB() as db:
        for inbound_tag in config.inbounds_by_tag:
            inbound_hosts: Sequence[ProxyHost] = crud.get_hosts(db, inbound_tag)

            storage[inbound_tag] = [
                {
                    "remark": host.remark,
                    "address": resolve_host_addresses(host),
                    # Привязанные ноды хоста: по ним определяется БС-признак и БС-блокировки
                    # (NPVPN-1652), адрес хоста для этого не годится — он может быть доменом.
                    # Инвариант: адреса и node_ids строятся по одному множеству нод —
                    # обе функции живут рядом в host_addresses.py.
                    "node_ids": resolve_host_node_ids(host),
                    "port": host.port,
                    "path": host.path if host.path else None,
                    "sni": [i.strip() for i in host.sni.split(",")] if host.sni else [],
                    "host": [i.strip() for i in host.host.split(",")] if host.host else [],
                    "alpn": host.alpn.value,
                    "fingerprint": host.fingerprint.value,
                    # None means the tls is not specified by host itself and
                    #  complies with its inbound's settings.
                    "tls": None if host.security == ProxyHostSecurity.inbound_default else host.security.value,
                    "allowinsecure": host.allowinsecure,
                    "mux_enable": host.mux_enable,
                    "fragment_setting": host.fragment_setting,
                    "noise_setting": host.noise_setting,
                    "random_user_agent": host.random_user_agent,
                    "use_sni_as_host": host.use_sni_as_host,
                    "bot_usernames": host.bot_usernames,
                    "xhttp_extra": host.xhttp_extra,
                    "order": host.order,
                }
                for host in inbound_hosts
                if not host.is_disabled
            ]


__all__ = [
    "config",
    "hosts",
    "core",
    "api",
    "nodes",
    "master_inbound_tags",
    "operations",
    "exceptions",
    "exc",
    "types",
    "XRayConfig",
    "XRayCore",
    "XRayNode",
]
