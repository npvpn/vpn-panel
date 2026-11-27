from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from app.models.managed import ManagedBotSettingsPayload
from app.models.settings import PANEL_SETTING_KEYS, SUBSCRIPTION_MESSAGE_KEYS

if TYPE_CHECKING:
    # Отложенный импорт: app.db тянет SQLAlchemy-модели и подключение к БД,
    # которые не нужны чистой функции validate_managed_payload и не должны
    # тянуться при импорте модуля (см. crud-функции ниже — там app.db
    # импортируется лениво, внутри функций, которым реально нужна db).
    from app.db import Session

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ManagedSection:
    key: str
    scope: str
    validate: Callable[[dict[str, Any]], dict[str, Any]]


MANAGED_SECTIONS: dict[str, ManagedSection] = {}

BOT_SETTINGS_KEY = "bot_settings"
BOT_MANAGED_IDENTITY_FIELDS = frozenset({"username", "title", "web_url"})
BOT_MANAGED_JSON_FIELDS = frozenset(
    {
        "bot_url",
        "web_url",
        "sub_support_url",
        "sub_subscription_domain",
        "sub_pay_url",
        "chat_base_url",
        "chat_website_token",
        "chat_identity_url",
        "show_ads",
        "sub_profile_url",
        # Заголовок профиля задаётся только в панели, отдельно на каждого бота.
        # Старый пуш ещё может прислать public_name — поле принимается схемой, но не пишется.
        # Интервал обновления профиля теперь принадлежит настройкам панели.
        # Поле по-прежнему принимается схемой старого managed-пуша, но не пишется.
        "bs_extra_reset_pool_on_prolong",
    }
)
BOT_MANAGED_SETTINGS_FIELDS = BOT_MANAGED_IDENTITY_FIELDS | BOT_MANAGED_JSON_FIELDS


def _validate_bot_settings(data: dict[str, Any]) -> dict[str, Any]:
    # Старые клиенты ещё шлют panel-wide тексты; extra=forbid иначе роняет весь синк.
    cleaned = {key: value for key, value in data.items() if key not in SUBSCRIPTION_MESSAGE_KEYS}
    normalized = ManagedBotSettingsPayload.model_validate(cleaned).model_dump()
    normalized["web_url"] = _normalize_web_url(normalized["web_url"])
    return normalized


MANAGED_BOT_SECTIONS: dict[str, ManagedSection] = {
    BOT_SETTINGS_KEY: ManagedSection(key=BOT_SETTINGS_KEY, scope="bot", validate=_validate_bot_settings),
}


class AdminSyncDisabledError(Exception):
    pass


class ManagedBotConflictError(Exception):
    pass


class ManagedFieldChangeError(Exception):
    pass


def _normalize_web_url(value: Any) -> str:
    domain = str(value or "").strip().replace("https://", "").replace("http://", "").strip("/")
    return f"https://{domain}" if domain else ""


def bot_managed_state_key(source_bot_id: int) -> str:
    return f"{BOT_SETTINGS_KEY}:{source_bot_id}"


def _forget_managed_bot_state(db: Session, source_bot_id: int | None) -> None:
    """Убрать пометку старого source_bot_id, когда строка панели перепривязывается."""
    if source_bot_id is None:
        return
    from app.db.models import ManagedSetting

    db.query(ManagedSetting).filter(ManagedSetting.key == bot_managed_state_key(int(source_bot_id))).delete(
        synchronize_session=False
    )


def validate_managed_payload(key: str, data: dict[str, Any]) -> dict[str, Any]:
    section = MANAGED_SECTIONS[key]  # KeyError для неизвестного ключа
    return section.validate(data)


def apply_managed_push(db: Session, key: str, *, data: dict[str, Any], version: str, source: str) -> dict[str, Any]:
    from app.db import crud

    section = MANAGED_SECTIONS[key]
    normalized = section.validate(data)
    crud.upsert_global_setting(db, key, normalized)
    return _as_state(crud.upsert_managed_setting(db, key, scope=section.scope, source=source, version=version))


def read_managed_state(db: Session, key: str) -> dict[str, Any] | None:
    from app.db import crud

    row = crud.get_managed_setting(db, key)
    return _as_state(row) if row else None


def unlink_managed(db: Session, key: str) -> bool:
    from app.db import crud

    return crud.delete_managed_setting(db, key)


def apply_managed_bot_push(
    db: Session,
    key: str,
    source_bot_id: int,
    *,
    data: dict[str, Any],
    version: str,
    source: str,
) -> dict[str, Any]:
    section = MANAGED_BOT_SECTIONS[key]
    normalized = section.validate(data)
    logger.info(
        "managed bot push: key=%s source_bot_id=%s username=%s version=%s source=%s",
        key,
        source_bot_id,
        normalized.get("username"),
        version,
        source,
    )

    from app.db import crud

    # Тот же лок, что у ручного создания: два первых сервиса не должны оба
    # увидеть пустую панель и пропустить перенос привязок хостов.
    with crud._lock_bot_creation(db):
        return _apply_locked_managed_bot_push(
            db,
            source_bot_id,
            normalized=normalized,
            data=data,
            version=version,
            source=source,
            section=section,
        )


def _apply_locked_managed_bot_push(
    db: Session,
    source_bot_id: int,
    *,
    normalized: dict[str, Any],
    data: dict[str, Any],
    version: str,
    source: str,
    section: Any,
) -> dict[str, Any]:
    from app.db import crud
    from app.db.models import Bot, BotSettings, ManagedSetting, User

    bound = db.query(Bot).filter(Bot.source_bot_id == source_bot_id).first()
    username_match = db.query(Bot).filter(Bot.username == normalized["username"]).first()
    # Username в панели — тот бот, чьи настройки надо обновить. Старый source_bot_id
    # на той же строке остаётся после пересоздания бота в админке и не должен ронять очередь.
    # Чужую строку с пользователями или выключенным синком не отвязываем.
    if username_match is not None and not username_match.admin_sync_enabled:
        logger.warning(
            "managed bot push rejected: admin_sync_disabled panel_bot_id=%s username=%s source_bot_id=%s",
            username_match.id,
            username_match.username,
            source_bot_id,
        )
        raise AdminSyncDisabledError
    if username_match is not None and bound is not None and username_match.id != bound.id:
        bound_has_users = db.query(User.id).filter(User.bot_id == bound.id).first() is not None
        if bound_has_users or not bound.admin_sync_enabled:
            logger.warning(
                "managed bot push conflict: source_bot_id=%s stays on panel_bot_id=%s; username=%s is panel_bot_id=%s",
                source_bot_id,
                bound.id,
                normalized["username"],
                username_match.id,
            )
            raise ManagedBotConflictError("source_bot_id_conflict")
        previous_source_id = cast(int | None, bound.source_bot_id)
        cast(Any, bound).source_bot_id = None
        db.flush()
        _forget_managed_bot_state(db, previous_source_id)
        logger.info(
            "managed bot push: detached empty source_bot_id=%s from panel_bot_id=%s; username=%s stays on panel_bot_id=%s",
            previous_source_id,
            bound.id,
            normalized["username"],
            username_match.id,
        )
    bot: Any = username_match or bound
    if bot is not None and username_match is None and not bot.admin_sync_enabled:
        logger.warning(
            "managed bot push rejected: admin_sync_disabled panel_bot_id=%s username=%s source_bot_id=%s",
            bot.id,
            bot.username,
            source_bot_id,
        )
        raise AdminSyncDisabledError
    if bot is not None and bot.source_bot_id not in (None, source_bot_id):
        logger.info(
            "managed bot push: rebind username=%s panel_bot_id=%s source_bot_id %s -> %s",
            bot.username,
            bot.id,
            bot.source_bot_id,
            source_bot_id,
        )
        _forget_managed_bot_state(db, cast(int | None, bot.source_bot_id))

    if bot is None:
        is_first_bot = crud.count_bots(db) == 0
        crud.bind_all_hosts_to_only_bot(db)
        bot = Bot(
            username=normalized["username"],
            title=normalized["title"],
            source_bot_id=source_bot_id,
            admin_sync_enabled=True,
        )
        db.add(bot)
        db.flush()
        if is_first_bot:
            db.query(User).update({User.bot_id: bot.id}, synchronize_session=False)
        logger.info(
            "managed bot push: created panel bot id=%s username=%s source_bot_id=%s",
            bot.id,
            bot.username,
            source_bot_id,
        )

    bot_row = cast(Any, bot)
    bot_row.source_bot_id = source_bot_id
    bot_row.username = normalized["username"]
    bot_row.title = normalized["title"]

    settings = db.query(BotSettings).filter(BotSettings.bot_id == bot.id).first()
    if settings is None:
        settings = BotSettings(bot_id=bot.id, data={})
        db.add(settings)
    merged = dict(settings.data or {})
    for key in PANEL_SETTING_KEYS:
        merged.pop(key, None)
    for field in BOT_MANAGED_JSON_FIELDS:
        if field not in data:
            continue
        merged[field] = normalized[field]
    cast(Any, settings).data = merged

    state_key = bot_managed_state_key(source_bot_id)
    state = db.query(ManagedSetting).filter(ManagedSetting.key == state_key).first()
    if state is None:
        state = ManagedSetting(key=state_key, scope=section.scope, source=source, version=version)
        db.add(state)
    else:
        state_row = cast(Any, state)
        state_row.scope = section.scope
        state_row.source = source
        state_row.version = version
        state_row.applied_at = datetime.utcnow()

    db.commit()
    db.refresh(state)
    logger.info(
        "managed bot push applied: panel_bot_id=%s source_bot_id=%s state_key=%s version=%s",
        bot.id,
        source_bot_id,
        state.key,
        state.version,
    )
    return _as_state(
        {
            "key": state.key,
            "version": state.version,
            "source": state.source,
            "applied_at": state.applied_at,
        }
    )


def read_managed_bot_state(db: Session, key: str, source_bot_id: int) -> dict[str, Any] | None:
    from app.db import crud

    bot = crud.get_bot_by_source_id(db, source_bot_id)
    if bot is None:
        return None
    if not bot.admin_sync_enabled:
        raise AdminSyncDisabledError
    return read_managed_state(db, bot_managed_state_key(source_bot_id))


def read_bot_managed_state(db: Session, bot: Any) -> dict[str, Any] | None:
    if bot.source_bot_id is None:
        return None
    return read_managed_state(db, bot_managed_state_key(int(bot.source_bot_id)))


def set_bot_admin_sync(db: Session, bot: Any, enabled: bool) -> None:
    from app.db.models import ManagedSetting

    previous = bool(bot.admin_sync_enabled)
    bot.admin_sync_enabled = enabled
    if not enabled and bot.source_bot_id is not None:
        deleted = (
            db.query(ManagedSetting)
            .filter(ManagedSetting.key == bot_managed_state_key(int(bot.source_bot_id)))
            .delete(synchronize_session=False)
        )
        logger.info(
            "admin sync disabled for panel bot id=%s username=%s source_bot_id=%s unlinked=%s",
            bot.id,
            bot.username,
            bot.source_bot_id,
            deleted,
        )
    else:
        logger.info(
            "admin sync toggled for panel bot id=%s username=%s source_bot_id=%s %s -> %s",
            bot.id,
            bot.username,
            bot.source_bot_id,
            previous,
            enabled,
        )
    db.commit()
    db.refresh(bot)


def ensure_bot_identity_update_allowed(
    db: Session,
    bot: Any,
    *,
    username: str,
    title: str | None,
    web_url: str | None,
) -> None:
    if read_bot_managed_state(db, bot) is None:
        return
    from app.db import crud
    from app.models.bot import apply_bot_settings_fallback

    current_settings = apply_bot_settings_fallback(crud.get_bot_settings(db, bot))
    requested = {
        "username": username.strip().lstrip("@"),
        "title": title.strip() if isinstance(title, str) and title.strip() else None,
        "web_url": _normalize_web_url(current_settings.get("web_url") if web_url is None else web_url),
    }
    current = {
        "username": bot.username,
        "title": bot.title,
        "web_url": _normalize_web_url(current_settings.get("web_url")),
    }
    if requested != current:
        raise ManagedFieldChangeError


def ensure_bot_settings_update_allowed(db: Session, bot: Any, data: dict[str, Any]) -> None:
    if read_bot_managed_state(db, bot) is None:
        return
    from app.db import crud
    from app.models.bot import apply_bot_settings_fallback

    current = apply_bot_settings_fallback(crud.get_bot_settings(db, bot))
    for field in BOT_MANAGED_JSON_FIELDS:
        requested_value = _normalize_web_url(data[field]) if field == "web_url" else data[field]
        current_value = _normalize_web_url(current[field]) if field == "web_url" else current[field]
        if requested_value != current_value:
            raise ManagedFieldChangeError


def _as_state(row: dict[str, Any]) -> dict[str, Any]:
    return {"key": row["key"], "version": row["version"], "source": row["source"], "applied_at": row["applied_at"]}
