"""Кэш пер-нодного xray-конфига (NPVPN-1727).

Волна переподключения нод заставляла панель сериализовать полный конфиг со всеми
активными пользователями заново на каждую ноду; 20 таких to_json параллельно душили GIL
и роняли p99 /sub. Здесь пайплайн сборки конфига под конкретную ноду и кэш готовой
JSON-строки по «сигнатуре» ноды (инбаунды + cascade + блокировки), общий на волну.

Без тяжёлых импортов (app.db, config, xray_api) — тестируется как inbound_filter/cascade.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Collection, Iterable

from app.xray.bs_limit import strip_blocked_clients
from app.xray.cascade_config import cascade_config
from app.xray.inbound_filter import apply_inbound_filter


def node_has_inbound(node_inbound_tags: Collection[str] | None, inbound_tag: str) -> bool:
    """Реально ли inbound_tag включён на ноде (по факту её последнего start/restart).

    Пусто/None (ещё не знаем ДО первого коннекта, либо на ноде НЕ отмечено ни
    одного инбаунда) → не фильтруем: см. apply_inbound_filter — та же
    конвенция «пустой allowed_tags = поднимаются все инбаунды», так что нода
    без единой галочки реально гоняет xray со всеми тегами.
    """
    return not node_inbound_tags or inbound_tag in node_inbound_tags


def node_signature(
    node_inbound_tags: Iterable[str] | None,
    cascade_kwargs: dict,
    blocked_user_ids: Iterable[int] | None,
) -> tuple:
    """Детерминированный хэшируемый ключ пер-нодного конфига.

    Всё, что различает итоговый конфиг ноды: набор инбаундов, cascade-параметры и
    множество заблокированных user_id. Ноды с одинаковой сигнатурой получают один
    и тот же JSON из кэша; direct-ноды без блокировок → общий ключ.
    """
    return (
        tuple(sorted(node_inbound_tags or ())),
        json.dumps(cascade_kwargs or {}, sort_keys=True, default=str),
        tuple(sorted(blocked_user_ids or ())),
    )


def build_node_config_json(
    base_config,
    node_inbound_tags: Iterable[str] | None,
    cascade_kwargs: dict,
    blocked_user_ids: Iterable[int] | None,
) -> str:
    """Собрать конфиг под ноду и сериализовать в JSON (без кэша)."""
    cfg = strip_blocked_clients(
        cascade_config(apply_inbound_filter(base_config, node_inbound_tags), **(cascade_kwargs or {})),
        blocked_user_ids,
    )
    return cfg.to_json()


def inline_local_certificates(config: dict) -> dict:
    """Заменить certificateFile/keyFile инбаундов на inline certificate/key (список строк).

    Раньше это делал XRayNode._prepare_config на каждую ноду перед сериализацией. Вынесено
    сюда, чтобы вызвать один раз в include_db_users() до сериализации/шаринга. Идемпотентно:
    если certificateFile уже заменён — второй проход ничего не делает.
    """
    for inbound in config.get("inbounds", []):
        stream_settings = inbound.get("streamSettings") or {}
        tls_settings = stream_settings.get("tlsSettings") or {}
        for certificate in tls_settings.get("certificates") or []:
            if certificate.get("certificateFile"):
                with open(certificate["certificateFile"]) as file:
                    certificate["certificate"] = [line.strip() for line in file.readlines()]
                    del certificate["certificateFile"]
            if certificate.get("keyFile"):
                with open(certificate["keyFile"]) as file:
                    certificate["key"] = [line.strip() for line in file.readlines()]
                    del certificate["keyFile"]
    return config


class _NodeJsonCache:
    """Кэш готовой JSON-строки конфига по сигнатуре ноды. Живёт на объекте волнового
    конфига (см. node_config_json), поэтому автоматически сбрасывается со сменой волны.

    Лок сериализует тяжёлую питон-работу (build+to_json): в любой момент её делает
    максимум один поток — это снимает GIL-давление на горячий /sub. Худший случай гонки —
    один лишний build, не порча данных.
    """

    def __init__(self, base_config, build: Callable[..., str] = build_node_config_json):
        self._base = base_config
        self._build = build
        self._cache: dict[tuple, str] = {}
        self._lock = threading.Lock()
        self.build_count = 0

    def __deepcopy__(self, memo):
        # XRayConfig.copy() == deepcopy(self); the per-node config copies made during a
        # build are transient (serialized once, never re-cached or used as a wave base),
        # and threading.Lock can't be deep-copied. Share the cache by reference instead
        # of copying it — the copy's cache is never read.
        return self

    def get(
        self,
        node_inbound_tags: Iterable[str] | None,
        cascade_kwargs: dict,
        blocked_user_ids: Iterable[int] | None,
    ) -> str:
        key = node_signature(node_inbound_tags, cascade_kwargs, blocked_user_ids)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
            js = self._build(self._base, node_inbound_tags, cascade_kwargs, blocked_user_ids)
            self._cache[key] = js
            self.build_count += 1
            return js


_attach_lock = threading.Lock()


def node_config_json(
    base_config,
    node_inbound_tags: Iterable[str] | None,
    cascade_kwargs: dict,
    blocked_user_ids: Iterable[int] | None,
) -> str:
    """JSON конфига под ноду с кэшем на объекте волнового конфига.

    include_db_users() вешает свежий _NodeJsonCache на возвращаемый конфиг, поэтому все
    ноды одной волны шарят кэш. Для конфигов без атрибута (из файла/тестов) кэш создаётся
    лениво; если объект не принимает атрибут — работаем без шаринга (корректность цела).

    Ленивое создание кэша защищено отдельным модульным локом с double-checked locking:
    без него два потока, увидевшие отсутствие атрибута одновременно (старт волны, прод
    обычно подстрахован Task 5 — предзаполнением кэша до параллельных вызовов, но фасад
    не должен на это молча полагаться), создали бы каждый свой _NodeJsonCache и билдили
    бы независимо — та же проблема гонки, которую решает лок внутри _NodeJsonCache.get(),
    только на шаг раньше.
    """
    cache = getattr(base_config, "_node_json_cache", None)
    if cache is None:
        with _attach_lock:
            cache = getattr(base_config, "_node_json_cache", None)  # re-check под локом
            if cache is None:
                cache = _NodeJsonCache(base_config)
                try:
                    base_config._node_json_cache = cache
                except (AttributeError, TypeError):
                    pass  # объект не принимает атрибут — работаем без шаринга
    return cache.get(node_inbound_tags, cascade_kwargs, blocked_user_ids)
