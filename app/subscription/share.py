import base64
import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime as dt
from datetime import timedelta
from typing import TYPE_CHECKING, Literal, cast

from jdatetime import date as jd

from app import xray
from app.subscription.address_context import AddressContext
from app.subscription.bs_context import ZERO_STUB, BsContext, StubEndpoint
from app.subscription.host_candidates import compose_endpoints, prepare_candidates
from app.utils.system import get_public_ip, get_public_ipv6, readable_size
from app.xray.host_injection import InjectionError

from . import *

if TYPE_CHECKING:
    from app.db import Session
    from app.models.user import UserResponse

from config import (
    ACTIVE_STATUS_TEXT,
    DISABLED_STATUS_TEXT,
    EXPIRED_STATUS_TEXT,
    LIMITED_STATUS_TEXT,
    ONHOLD_STATUS_TEXT,
)

logger = logging.getLogger("app.subscription.share")

SERVER_IP = get_public_ip()
SERVER_IPV6 = get_public_ipv6()

STATUS_EMOJIS = {
    "active": "✅",
    "expired": "⌛️",
    "limited": "🪫",
    "disabled": "❌",
    "on_hold": "🔌",
}

STATUS_TEXTS = {
    "active": ACTIVE_STATUS_TEXT,
    "expired": EXPIRED_STATUS_TEXT,
    "limited": LIMITED_STATUS_TEXT,
    "disabled": DISABLED_STATUS_TEXT,
    "on_hold": ONHOLD_STATUS_TEXT,
}


SubscriptionConf = (
    V2rayShareLink
    | V2rayJsonConfig
    | SingBoxConfiguration
    | ClashConfiguration
    | ClashMetaConfiguration
    | OutlineConfiguration
)

CONF_FACTORIES: dict[str, Callable[[], SubscriptionConf]] = {
    "v2ray": V2rayShareLink,
    "clash": ClashConfiguration,
    "clash-meta": ClashMetaConfiguration,
    "sing-box": SingBoxConfiguration,
    "outline": OutlineConfiguration,
}


def _render(
    render_format: str,
    *,
    proxies: dict,
    inbounds: dict,
    extra_data: dict,
    reverse: bool,
    bs: BsContext | None = None,
    stub: StubEndpoint | None = None,
    conf: SubscriptionConf | None = None,
    subset: AddressContext | None = None,
    bs_usage_suffix: Callable[[], str] | None = None,
    template_for: Callable[[dict], dict] | None = None,
) -> list | str:
    """Единая точка рендера: формат → класс конфига → process_inbounds_and_tags.

    conf передаётся готовым только для v2ray-json (его конструктор принимает карту
    документов клиентского конфига из app.services.xray_templates).
    """
    if conf is None:
        factory = CONF_FACTORIES.get(render_format)
        if factory is None:
            raise ValueError(f'Unsupported format "{render_format}"')
        conf = factory()
    return process_inbounds_and_tags(
        inbounds,
        proxies,
        setup_format_variables(extra_data),
        conf=conf,
        reverse=reverse,
        bs=bs,
        stub=stub,
        subset=subset,
        bs_usage_suffix=bs_usage_suffix,
        template_for=template_for,
    )


def generate_v2ray_links(
    proxies: dict,
    inbounds: dict,
    extra_data: dict,
    reverse: bool,
    bs: BsContext | None = None,
    stub: StubEndpoint | None = None,
    subset: AddressContext | None = None,
) -> list:
    from app.services.xray_templates import build_template_lookup, get_cached_active_bodies

    lookup = build_template_lookup(get_cached_active_bodies())
    return cast(
        list,
        _render(
            "v2ray",
            proxies=proxies,
            inbounds=inbounds,
            extra_data=extra_data,
            reverse=reverse,
            bs=bs,
            stub=stub,
            subset=subset,
            template_for=lambda host: lookup(host.get("client_config_id")),
        ),
    )


def generate_subscription(
    user: "UserResponse",
    config_format: str,
    as_base64: bool,
    reverse: bool,
    revoked: bool = False,
    expired: bool = False,
    device_limited: bool = False,
    device_limited_hard: bool = False,
    unsupported_client: bool = False,
    settings: dict | None = None,
    bs: BsContext | None = None,
    db: "Session | None" = None,
    subset: AddressContext | None = None,
    bs_usage_suffix: Callable[[], str] | None = None,
) -> str:
    bs = bs or BsContext.empty()
    from app.models.settings import overlay_subscription_messages
    from config import USE_CUSTOM_JSON_DEFAULT

    # Тексты — из panel overlay (HTTP уже наложил их в build_render_context).
    resolved_settings = overlay_subscription_messages(settings or {}, None)

    # Тела документов клиентского конфига живут в app.services.xray_templates
    # (документы с историей, NPVPN-2024) и читаются через процессный кэш
    # get_cached_active_bodies — без запроса к БД на каждую подписку. Привязка лежит
    # прямо на хосте (host["client_config_id"]), поэтому карта нод больше не нужна.
    # db здесь — признак «настоящий запрос»: без него v2ray-json рендерится файловым
    # шаблоном, тот же фолбэк, что и раньше для пустых настроек.
    client_configs: dict[int, dict] = {}
    default_config_id: int | None = None
    if db is not None:
        from app.services.xray_templates import get_cached_active_bodies
        from app.xray.client_configs import parse_json_object

        def _safe_json(raw, name):
            try:
                return parse_json_object(raw)
            except ValueError as exc:
                logger.warning("[sub] invalid %s", name)
                return {"npvpn": None}

        # Процессный кэш (не db.info): /sub/ — горячий путь, обычный запрос БД на КАЖДУЮ
        # подписку недопустим (раньше шаблон/routing читались из уже загруженного
        # panel_settings, без лишнего JOIN). Инвалидируется через
        # app.services.xray_templates.invalidate при любой записи версии (Task 3).
        bodies = get_cached_active_bodies()
        client_configs = {
            config_id: parsed
            for config_id, raw in bodies.get("configs", {}).items()
            if (parsed := _safe_json(raw, f"client config {config_id}")) is not None
        }
        # Вторая ступень фолбэка (NPVPN-2024): хост без собственной привязки — так
        # миграция оставляет все не-БС-хосты — получает документ `default` целиком.
        default_config_id = bodies.get("default_id")

    from app.templates import render_template
    from app.xray.client_configs import make_template_lookup
    from config import V2RAY_SUBSCRIPTION_TEMPLATE

    template_lookup = make_template_lookup(
        client_configs, default_config_id, lambda: render_template(V2RAY_SUBSCRIPTION_TEMPLATE)
    )
    render_format = config_format
    if config_format == "incy":
        render_format = "v2ray-json" if USE_CUSTOM_JSON_DEFAULT else "v2ray"
        as_base64 = render_format == "v2ray"

    incy_v2ray_mode = config_format == "incy" and render_format == "v2ray"

    # Special handling for inactive tokens: placeholder nodes for V2Ray/INCY
    if render_format in ("v2ray", "v2ray-json") and (revoked or expired or unsupported_client or device_limited_hard):
        from app.subscription.sub_stub import build_v2ray_status_stub, pick_status_stub_text_list

        text_list = pick_status_stub_text_list(
            revoked=revoked,
            expired=expired,
            device_limited_hard=device_limited_hard,
            unsupported_client=unsupported_client,
            settings=resolved_settings,
        )
        return build_v2ray_status_stub(
            text_list,
            cast(Literal["v2ray", "v2ray-json"], render_format),
            as_base64=as_base64,
            reverse=reverse,
            v2ray_stub_profile="incy" if incy_v2ray_mode else "default",
        )

    device_limit_links = []
    device_limit_text = []
    if render_format in ("v2ray", "v2ray-json") and device_limited and not device_limited_hard:
        from app.subscription.v2ray import V2rayShareLink

        device_limit_text = resolved_settings["sub_device_limit_server_text"] or []
        if render_format == "v2ray" and device_limit_text:
            if incy_v2ray_mode:
                from app.subscription.sub_stub import INCY_STUB_ADDRESS, INCY_STUB_ID, INCY_STUB_PORT

                stub_address = INCY_STUB_ADDRESS
                stub_port = INCY_STUB_PORT
                stub_id = INCY_STUB_ID
            else:
                stub_address = "0.0.0.0"
                stub_port = 0
                stub_id = "00000000-0000-0000-0000-000000000000"
            device_limit_links = [
                V2rayShareLink.vless(
                    remark=remark,
                    address=stub_address,
                    port=stub_port,
                    id=stub_id,
                    net="ws",
                    tls="none",
                    path="",
                    host="",
                )
                for remark in device_limit_text
            ]

    # БС-заглушки на месте: заблокированные БС-теги остаются в подписке, но их
    # хосты рендерятся как мёртвые заглушки. Прокидываем во все форматы.
    if incy_v2ray_mode:
        from app.subscription.sub_stub import INCY_STUB_ADDRESS, INCY_STUB_PORT

        stub = StubEndpoint(address=INCY_STUB_ADDRESS, port=INCY_STUB_PORT)
    elif render_format == "v2ray-json":
        from app.subscription.sub_stub import JSON_STUB_ADDRESS, JSON_STUB_PORT

        stub = StubEndpoint(address=JSON_STUB_ADDRESS, port=JSON_STUB_PORT)
    else:
        stub = ZERO_STUB

    if render_format == "v2ray":
        links = cast(
            list,
            _render(
                "v2ray",
                proxies=user.proxies,
                inbounds=user.inbounds,
                extra_data=user.__dict__,
                reverse=reverse,
                bs=bs,
                stub=stub,
                subset=subset,
                bs_usage_suffix=bs_usage_suffix,
                template_for=lambda host: template_lookup(host.get("client_config_id")),
            ),
        )
        if device_limit_links:
            links = [*device_limit_links, *links]
        config = "\n".join(links)
    elif render_format in ("clash-meta", "clash", "sing-box", "outline"):
        config = cast(
            str,
            _render(
                render_format,
                proxies=user.proxies,
                inbounds=user.inbounds,
                extra_data=user.__dict__,
                reverse=reverse,
                bs=bs,
                stub=stub,
                subset=subset,
                bs_usage_suffix=bs_usage_suffix,
                template_for=lambda host: template_lookup(host.get("client_config_id")),
            ),
        )
    elif render_format == "v2ray-json":
        from app.subscription.sub_stub import JSON_STUB_ADDRESS, JSON_STUB_ID, JSON_STUB_PORT
        from app.subscription.v2ray import V2rayJsonConfig

        conf = V2rayJsonConfig(configs=client_configs, default_id=default_config_id)
        if device_limit_text:
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
            for remark in device_limit_text:
                conf.add(
                    remark=remark,
                    address=JSON_STUB_ADDRESS,
                    inbound=stub_inbound,
                    settings={"id": JSON_STUB_ID},
                )
        config = cast(
            str,
            _render(
                "v2ray-json",
                proxies=user.proxies,
                inbounds=user.inbounds,
                extra_data=user.__dict__,
                reverse=reverse,
                bs=bs,
                stub=stub,
                conf=conf,
                subset=subset,
                bs_usage_suffix=bs_usage_suffix,
                template_for=lambda host: template_lookup(host.get("client_config_id")),
            ),
        )
    else:
        raise ValueError(f'Unsupported format "{config_format}"')

    if as_base64:
        config = base64.b64encode(config.encode()).decode()

    return config


def format_time_left(seconds_left: int) -> str:
    if not seconds_left or seconds_left <= 0:
        return "∞"

    minutes, seconds = divmod(seconds_left, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    months, days = divmod(days, 30)

    result = []
    if months:
        result.append(f"{months}m")
    if days:
        result.append(f"{days}d")
    if hours and (days < 7):
        result.append(f"{hours}h")
    if minutes and not (months or days):
        result.append(f"{minutes}m")
    if seconds and not (months or days):
        result.append(f"{seconds}s")
    return " ".join(result)


def setup_format_variables(extra_data: dict) -> dict:
    from app.models.user import UserStatus

    user_status = extra_data.get("status")
    expire_timestamp = extra_data.get("expire")
    on_hold_expire_duration = extra_data.get("on_hold_expire_duration")
    now = dt.utcnow()
    now_ts = now.timestamp()

    if user_status != UserStatus.on_hold:
        if expire_timestamp is not None and expire_timestamp >= 0:
            seconds_left = expire_timestamp - int(dt.utcnow().timestamp())
            expire_datetime = dt.fromtimestamp(expire_timestamp)
            expire_date = expire_datetime.date()
            jalali_expire_date = jd.fromgregorian(
                year=expire_date.year, month=expire_date.month, day=expire_date.day
            ).strftime("%Y-%m-%d")
            if now_ts < expire_timestamp:
                days_left = (expire_datetime - dt.utcnow()).days + 1
                time_left = format_time_left(seconds_left)
            else:
                days_left = "0"
                time_left = "0"

        else:
            days_left = "∞"
            time_left = "∞"
            expire_date = "∞"
            jalali_expire_date = "∞"
    else:
        if on_hold_expire_duration is not None and on_hold_expire_duration >= 0:
            days_left = timedelta(seconds=on_hold_expire_duration).days
            time_left = format_time_left(on_hold_expire_duration)
            expire_date = "-"
            jalali_expire_date = "-"
        else:
            days_left = "∞"
            time_left = "∞"
            expire_date = "∞"
            jalali_expire_date = "∞"

    if extra_data.get("data_limit"):
        data_limit = readable_size(extra_data["data_limit"])
        data_left = extra_data["data_limit"] - extra_data["used_traffic"]
        if data_left < 0:
            data_left = 0
        data_left = readable_size(data_left)
    else:
        data_limit = "∞"
        data_left = "∞"

    status_emoji = STATUS_EMOJIS.get(extra_data.get("status")) or ""
    status_text = STATUS_TEXTS.get(extra_data.get("status")) or ""

    format_variables = defaultdict(
        lambda: "<missing>",
        {
            "SERVER_IP": SERVER_IP,
            "SERVER_IPV6": SERVER_IPV6,
            "USERNAME": extra_data.get("username", "{USERNAME}"),
            "DATA_USAGE": readable_size(extra_data.get("used_traffic")),
            "DATA_LIMIT": data_limit,
            "DATA_LEFT": data_left,
            "DAYS_LEFT": days_left,
            "EXPIRE_DATE": expire_date,
            "JALALI_EXPIRE_DATE": jalali_expire_date,
            "TIME_LEFT": time_left,
            "STATUS_EMOJI": status_emoji,
            "STATUS_TEXT": status_text,
            "BOT_USERNAME": extra_data.get("bot_username"),
        },
    )

    return format_variables


def process_inbounds_and_tags(
    inbounds: dict,
    proxies: dict,
    format_variables: dict,
    conf: V2rayShareLink
    | V2rayJsonConfig
    | SingBoxConfiguration
    | ClashConfiguration
    | ClashMetaConfiguration
    | OutlineConfiguration,
    reverse=False,
    bs: BsContext | None = None,
    stub: StubEndpoint | None = None,
    subset: AddressContext | None = None,
    bs_usage_suffix: Callable[[], str] | None = None,
    template_for: Callable[[dict], dict] | None = None,
) -> list | str:
    bs = bs or BsContext.empty()
    stub = stub or ZERO_STUB
    if template_for is None:
        template_for = (
            (lambda host: conf.base_template(host.get("client_config_id")))
            if isinstance(conf, V2rayJsonConfig)
            else (lambda host: {})
        )
    candidates = prepare_candidates(
        inbounds,
        proxies,
        format_variables,
        inbounds_by_tag=xray.config.inbounds_by_tag,
        hosts_by_tag=xray.hosts,
        is_json=isinstance(conf, V2rayJsonConfig),
        template_for=template_for,
        bs=bs,
        stub=stub,
        subset=subset,
    )
    bs_usage_label = None

    def with_bs_label(remark, is_bs):
        nonlocal bs_usage_label
        if not is_bs or bs_usage_suffix is None:
            return remark
        if bs_usage_label is None:
            bs_usage_label = bs_usage_suffix()
        return remark + bs_usage_label

    def _candidate_order(item: dict) -> int:
        order = item.get("order")
        return int(order) if order is not None else 0

    candidates.sort(key=_candidate_order)

    for item in candidates:
        if item["host"].get("is_hidden"):
            continue
        if item["injection"] is not None:
            if not isinstance(conf, V2rayJsonConfig):
                continue
            try:
                endpoints, is_bs, all_blocked = compose_endpoints(item, candidates)
                if not endpoints:
                    if all_blocked:
                        conf.add_blocked(bs.stub_text, stub)
                    else:
                        logger.warning("Host %s: empty_injection", item["host"].get("id"))
                    continue
                conf.add_composed(
                    with_bs_label(item["remark"], is_bs),
                    endpoints,
                    item["host"].get("client_config_id"),
                    item["balancing"],
                )
            except InjectionError as exc:
                logger.warning("Host %s: %s", item["host"].get("id"), exc.code)
            continue
        if item["blocked"]:
            item["host_inbound"]["port"] = stub.port
            conf.add(
                remark=bs.stub_text,
                address=stub.address,
                inbound=item["host_inbound"],
                settings=item["settings"],
            )
            continue

        item["remark"] = with_bs_label(item["remark"], item["host"].get("is_bs"))
        if item["balanced"] and isinstance(conf, V2rayJsonConfig):
            conf.add_balanced(
                remark=item["remark"],
                addresses=item["addresses"],
                balancing=item["balancing"],
                inbound=item["host_inbound"],
                settings=item["settings"],
                **item["add_kwargs"],
            )
        else:
            conf.add(
                remark=item["remark"],
                address=item["address"],
                inbound=item["host_inbound"],
                settings=item["settings"],
                **item["add_kwargs"],
            )

    return conf.render(reverse=reverse)
