import os
from datetime import datetime
from typing import cast

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.sql.expression import select, text

from app import xray
from app.db.base import Base
from app.models.node import NodeBalancerStrategy, NodeProtocol, NodeRole, NodeStatus
from app.models.proxy import (
    ProxyHostALPN,
    ProxyHostFingerprint,
    ProxyHostSecurity,
    ProxyTypes,
)
from app.models.user import ReminderType, UserDataLimitResetStrategy, UserStatus

_UNSET = object()
"""Сентинел «кеш ещё не заполнен» — отличим от легитимного None в bs_monthly_limit_total."""

host_bot_association = Table(
    "host_bot_association",
    Base.metadata,
    Column("host_id", ForeignKey("hosts.id", ondelete="CASCADE"), primary_key=True),
    Column("bot_id", ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True),
)

host_nodes_association = Table(
    "host_nodes",
    Base.metadata,
    Column("host_id", ForeignKey("hosts.id", ondelete="CASCADE"), primary_key=True),
    Column("node_id", ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
)


class Admin(Base):
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True)
    username = Column(String(34), unique=True, index=True)
    hashed_password = Column(String(128))
    users = relationship("User", back_populates="admin")
    created_at = Column(DateTime, default=datetime.utcnow)
    is_sudo = Column(Boolean, default=False)
    password_reset_at = Column(DateTime, nullable=True)
    telegram_id = Column(BigInteger, nullable=True, default=None)
    discord_webhook = Column(String(1024), nullable=True, default=None)
    users_usage = Column(BigInteger, nullable=False, default=0)
    usage_logs = relationship("AdminUsageLogs", back_populates="admin")


class AdminUsageLogs(Base):
    __tablename__ = "admin_usage_logs"

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class Bot(Base):
    __tablename__ = "bots"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(128), nullable=True, default=None)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    users = relationship("User", back_populates="bot")
    settings = relationship("BotSettings", uselist=False, back_populates="bot", cascade="all, delete-orphan")
    hosts = relationship("ProxyHost", secondary=host_bot_association, back_populates="bots")


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id = Column(Integer, primary_key=True)
    bot_id = Column(Integer, ForeignKey("bots.id", ondelete="CASCADE"), unique=True, nullable=False)
    data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    bot = relationship("Bot", back_populates="settings")


class GlobalSetting(Base):
    __tablename__ = "global_settings"

    key = Column(String(64), primary_key=True)
    data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ManagedSetting(Base):
    __tablename__ = "managed_settings"

    key = Column(String(64), primary_key=True)
    scope = Column(String(16), nullable=False, default="global")
    source = Column(String(255), nullable=False, default="")
    version = Column(String(64), nullable=False, default="")
    applied_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(34, collation="NOCASE"), unique=True, index=True)
    proxies = relationship("Proxy", back_populates="user", cascade="all, delete-orphan")
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.active)
    used_traffic = Column(BigInteger, default=0)
    node_usages = relationship("NodeUserUsage", back_populates="user", cascade="all, delete-orphan")
    node_bs_usages = relationship("NodeUserBsUsage", back_populates="user", cascade="all, delete-orphan")
    notification_reminders = relationship("NotificationReminder", back_populates="user", cascade="all, delete-orphan")
    data_limit = Column(BigInteger, nullable=True)
    data_limit_reset_strategy = Column(
        Enum(UserDataLimitResetStrategy),
        nullable=False,
        default=UserDataLimitResetStrategy.no_reset,
    )
    usage_logs = relationship("UserUsageResetLogs", back_populates="user")  # maybe rename it to reset_usage_logs?
    expire = Column(Integer, nullable=True)
    admin_id = Column(Integer, ForeignKey("admins.id"))
    admin = relationship("Admin", back_populates="users")
    sub_revoked_at = Column(DateTime, nullable=True, default=None)
    sub_updated_at = Column(DateTime, nullable=True, default=None)
    sub_last_user_agent = Column(String(512), nullable=True, default=None)
    subscription_token = Column(String(256), nullable=True, default=None)
    bot_id = Column(Integer, ForeignKey("bots.id"), nullable=True, index=True)
    bot = relationship("Bot", back_populates="users")
    created_at = Column(DateTime, default=datetime.utcnow)
    note = Column(String(500), nullable=True, default=None)
    online_at = Column(DateTime, nullable=True, default=None)
    on_hold_expire_duration = Column(BigInteger, nullable=True, default=None)
    on_hold_timeout = Column(DateTime, nullable=True, default=None)
    device_limit = Column(Integer, nullable=True, default=None)
    bs_extra = Column(BigInteger, nullable=True, default=None)
    bs_extra_period = Column(String(7), nullable=True, default=None)

    # * Positive values: User will be deleted after the value of this field in days automatically.
    # * Negative values: User won't be deleted automatically at all.
    # * NULL: Uses global settings.
    auto_delete_in_days = Column(Integer, nullable=True, default=None)

    edit_at = Column(DateTime, nullable=True, default=None)
    last_status_change = Column(DateTime, default=datetime.utcnow, nullable=True)

    next_plan = relationship("NextPlan", uselist=False, back_populates="user", cascade="all, delete-orphan")
    devices = relationship("UserDevice", back_populates="user", cascade="all, delete-orphan")

    @hybrid_property
    def reseted_usage(self) -> int:
        return int(sum([log.used_traffic_at_reset for log in self.usage_logs]))

    @reseted_usage.expression
    def reseted_usage(cls):
        return (
            select(func.sum(UserUsageResetLogs.used_traffic_at_reset))
            .where(UserUsageResetLogs.user_id == cls.id)
            .label("reseted_usage")
        )

    @property
    def lifetime_used_traffic(self) -> int:
        return int(sum([log.used_traffic_at_reset for log in self.usage_logs]) + self.used_traffic)

    @property
    def bs_monthly_limit_total(self) -> int | None:
        """Месячный БС-потолок (лимит бота + купленный пул), None если лимит не задан.

        Значение кешируется на инстансе (`_bs_monthly_limit_total_cache`): `bs_monthly_used`
        обращается к этому свойству как к guard'у, а Pydantic при `UserResponse.model_validate`
        читает оба поля по отдельности — без кеша `normalize_bs_extra_period` (round-trip в БД)
        отрабатывал бы дважды на один ответ.
        """
        cached = self.__dict__.get("_bs_monthly_limit_total_cache", _UNSET)
        if cached is not _UNSET:
            return cast("int | None", cached)

        result = self._compute_bs_monthly_limit_total()
        self.__dict__["_bs_monthly_limit_total_cache"] = result
        return result

    def _compute_bs_monthly_limit_total(self) -> int | None:
        from sqlalchemy.orm import object_session

        from app.models.bot import apply_bot_settings_fallback
        from app.xray.bs_limit import monthly_effective_limit, period_keys

        if not self.bot or not self.bot.settings:
            return None
        settings = apply_bot_settings_fallback(self.bot.settings.data or {})
        monthly_limit = settings.get("bs_monthly_limit") or 0
        if not monthly_limit:
            return None

        db = object_session(self)
        if db is None:
            return monthly_effective_limit(monthly_limit, self.bs_extra or 0)

        from app.db.crud import normalize_bs_extra_period

        pool = normalize_bs_extra_period(
            db, cast(int, self.id), monthly_limit, period_keys(datetime.utcnow()), persist=False
        )
        return monthly_effective_limit(monthly_limit, pool)

    @property
    def bs_monthly_used(self) -> int:
        """Агрегат БС-расхода за текущий месяц из node_user_bs_usage."""
        if self.bs_monthly_limit_total is None:
            return 0
        from app.xray.bs_limit import aggregate_bs_usage, period_keys

        yyyymm = period_keys(datetime.utcnow())
        totals = aggregate_bs_usage(
            [
                {
                    "user_id": row.user_id,
                    "monthly_used": row.monthly_used,
                    "monthly_period": row.monthly_period,
                }
                for row in (self.node_bs_usages or [])
            ],
            yyyymm,
        )
        return totals.get(self.id, 0)

    @property
    def last_traffic_reset_time(self):
        return self.usage_logs[-1].reset_at if self.usage_logs else self.created_at

    @property
    def excluded_inbounds(self):
        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = [i.tag for i in proxy.excluded_inbounds]
        return _

    @property
    def inbounds(self):
        _ = {}
        for proxy in self.proxies:
            _[proxy.type] = []
            excluded_tags = [i.tag for i in proxy.excluded_inbounds]
            for inbound in xray.config.inbounds_by_protocol.get(proxy.type, []):
                if inbound["tag"] not in excluded_tags:
                    _[proxy.type].append(inbound["tag"])

        return _

    @property
    def bot_username(self):
        return self.bot.username if self.bot else None

    @property
    def subscription_url(self) -> str:
        """Absolute or path-only subscription link from bot domain / env prefix."""
        from app.subscription.bot_settings import resolve_bot_settings
        from app.subscription.subscription_url import build_subscription_url

        return build_subscription_url(
            cast(str | None, self.subscription_token),
            bot_settings=resolve_bot_settings(self),
        )


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (UniqueConstraint("user_id", "hwid", name="uq_user_devices_user_id_hwid"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user = relationship("User", back_populates="devices")
    hwid = Column(String(128), nullable=False)
    device_os = Column(String(64), nullable=True)
    ver_os = Column(String(64), nullable=True)
    device_model = Column(String(128), nullable=True)
    user_agent = Column(String(512), nullable=True)
    status = Column(String(16), nullable=False, default="active", server_default="active")
    first_seen = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


excluded_inbounds_association = Table(
    "exclude_inbounds_association",
    Base.metadata,
    Column("proxy_id", ForeignKey("proxies.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)

template_inbounds_association = Table(
    "template_inbounds_association",
    Base.metadata,
    Column("user_template_id", ForeignKey("user_templates.id")),
    Column("inbound_tag", ForeignKey("inbounds.tag")),
)

node_inbounds_association = Table(
    "node_inbounds",
    Base.metadata,
    Column("node_id", ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True),
    Column("inbound_tag", ForeignKey("inbounds.tag", ondelete="CASCADE"), primary_key=True),
)

master_inbounds_association = Table(
    "master_inbounds",
    Base.metadata,
    Column("inbound_tag", ForeignKey("inbounds.tag", ondelete="CASCADE"), primary_key=True),
)


class CascadeRoute(Base):
    """Связь входной ноды с выходной по конкретному инбаунду (NPVPN-1472).

    entry_node → exit_node: трафик с entry_inbound_tag на входной заворачивается
    в cascade-outbound на exit_node через cascade_inbound_tag (каталожный инбаунд
    выходной). Одна входная → N строк (1→N).
    """

    __tablename__ = "cascade_routes"

    id = Column(Integer, primary_key=True)
    entry_node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    exit_node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    entry_inbound_tag = Column(String(256), ForeignKey("inbounds.tag", ondelete="CASCADE"), nullable=False)
    cascade_inbound_tag = Column(String(256), ForeignKey("inbounds.tag", ondelete="CASCADE"), nullable=False)

    exit_node = relationship("Node", foreign_keys=[exit_node_id])


class NextPlan(Base):
    __tablename__ = "next_plans"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    data_limit = Column(BigInteger, nullable=False)
    expire = Column(Integer, nullable=True)
    add_remaining_traffic = Column(Boolean, nullable=False, default=False, server_default="0")
    fire_on_either = Column(Boolean, nullable=False, default=True, server_default="0")

    user = relationship("User", back_populates="next_plan")


class UserTemplate(Base):
    __tablename__ = "user_templates"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), nullable=False, unique=True)
    data_limit = Column(BigInteger, default=0)
    expire_duration = Column(BigInteger, default=0)  # in seconds
    username_prefix = Column(String(20), nullable=True)
    username_suffix = Column(String(20), nullable=True)

    inbounds = relationship("ProxyInbound", secondary=template_inbounds_association)


class UserUsageResetLogs(Base):
    __tablename__ = "user_usage_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="usage_logs")
    used_traffic_at_reset = Column(BigInteger, nullable=False)
    reset_at = Column(DateTime, default=datetime.utcnow)


class Proxy(Base):
    __tablename__ = "proxies"
    __table_args__ = (UniqueConstraint("user_id", "type"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="proxies")
    type = Column(Enum(ProxyTypes), nullable=False)
    settings = Column(JSON, nullable=False)
    excluded_inbounds = relationship("ProxyInbound", secondary=excluded_inbounds_association)


class ProxyInbound(Base):
    __tablename__ = "inbounds"

    id = Column(Integer, primary_key=True)
    tag = Column(String(256), unique=True, nullable=False, index=True)
    hosts = relationship("ProxyHost", back_populates="inbound", cascade="all, delete-orphan")


class ProxyHost(Base):
    __tablename__ = "hosts"
    # __table_args__ = (
    #     UniqueConstraint('inbound_tag', 'remark'),
    # )

    id = Column(Integer, primary_key=True)
    remark = Column(String(256), unique=False, nullable=False)
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, nullable=True)
    path = Column(String(256), unique=False, nullable=True)
    sni = Column(String(1000), unique=False, nullable=True)
    host = Column(String(1000), unique=False, nullable=True)
    security = Column(
        Enum(ProxyHostSecurity),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.inbound_default,
    )
    alpn = Column(
        Enum(ProxyHostALPN),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name,
    )
    fingerprint = Column(
        Enum(ProxyHostFingerprint),
        unique=False,
        nullable=False,
        default=ProxyHostSecurity.none,
        server_default=ProxyHostSecurity.none.name,
    )

    inbound_tag = Column(String(256), ForeignKey("inbounds.tag"), nullable=False)
    inbound = relationship("ProxyInbound", back_populates="hosts")
    allowinsecure = Column(Boolean, nullable=True)
    is_disabled = Column(Boolean, nullable=True, default=False)
    mux_enable = Column(Boolean, nullable=False, default=False, server_default="0")
    fragment_setting = Column(String(100), nullable=True)
    noise_setting = Column(String(2000), nullable=True)
    random_user_agent = Column(Boolean, nullable=False, default=False, server_default="0")
    use_sni_as_host = Column(Boolean, nullable=False, default=False, server_default="0")
    xhttp_extra = Column(JSON, nullable=True)
    bots = relationship("Bot", secondary=host_bot_association, back_populates="hosts")

    @property
    def bot_usernames(self):
        return [bot.username for bot in self.bots]

    nodes = relationship("Node", secondary=host_nodes_association, passive_deletes=True)

    @property
    def node_ids(self):
        return [node.id for node in self.nodes]


class System(Base):
    __tablename__ = "system"

    id = Column(Integer, primary_key=True)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class JWT(Base):
    __tablename__ = "jwt"

    id = Column(Integer, primary_key=True)
    secret_key = Column(String(64), nullable=False, default=lambda: os.urandom(32).hex())


class TLS(Base):
    __tablename__ = "tls"

    id = Column(Integer, primary_key=True)
    key = Column(String(4096), nullable=False)
    certificate = Column(String(2048), nullable=False)


class Node(Base):
    __tablename__ = "nodes"

    id = Column(Integer, primary_key=True)
    name = Column(String(256, collation="NOCASE"), unique=True)
    address = Column(String(256), unique=False, nullable=False)
    port = Column(Integer, unique=False, nullable=False)
    api_port = Column(Integer, unique=False, nullable=False)
    protocol = Column(
        Enum(NodeProtocol),
        nullable=False,
        default=NodeProtocol.rest,
        server_default=NodeProtocol.rest.value,
    )
    xray_version = Column(String(32), nullable=True)
    status = Column(Enum(NodeStatus), nullable=False, default=NodeStatus.connecting)
    last_status_change = Column(DateTime, default=datetime.utcnow)
    message = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)
    user_usages = relationship("NodeUserUsage", back_populates="node", cascade="all, delete-orphan")
    usages = relationship("NodeUsage", back_populates="node", cascade="all, delete-orphan")
    usage_coefficient = Column(Float, nullable=False, server_default=text("1.0"), default=1)
    inbounds = relationship(
        "ProxyInbound",
        secondary=node_inbounds_association,
        passive_deletes=True,
    )
    role = Column(
        Enum(NodeRole),
        nullable=False,
        default=NodeRole.direct,
        server_default=NodeRole.direct.value,
    )
    cascade_params = Column(JSON, nullable=True)
    cascade_routes = relationship(
        "CascadeRoute",
        foreign_keys="CascadeRoute.entry_node_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    cascade_balancer_strategy = Column(
        # values_callable: persist enum *values* (e.g. "leastLoad"), not member
        # names ("least_load"). The migration declares the SQL ENUM by value, so
        # without this SQLAlchemy would send names and MySQL truncates the column.
        Enum(NodeBalancerStrategy, values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=NodeBalancerStrategy.random,
        server_default=NodeBalancerStrategy.random.value,
    )
    is_bs = Column(Boolean, nullable=False, default=False, server_default=text("0"))


class NodeUserUsage(Base):
    __tablename__ = "node_user_usages"
    __table_args__ = (UniqueConstraint("created_at", "user_id", "node_id"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="node_usages")
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="user_usages")
    used_traffic = Column(BigInteger, default=0)


class NodeUserBsUsage(Base):
    """По-нодный инкрементальный счётчик расхода для БС-нод (NPVPN-1456).
    Ленивый сброс периодов при инкременте; единственный writer — record_usages."""

    __tablename__ = "node_user_bs_usage"
    __table_args__ = (UniqueConstraint("node_id", "user_id", name="uq_node_user_bs_usage"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    monthly_used = Column(BigInteger, nullable=False, default=0, server_default=text("0"))
    monthly_period = Column(String(7), nullable=True)  # "YYYY-MM"
    user = relationship("User", back_populates="node_bs_usages")


class NodeUserBlock(Base):
    """Текущее состояние по-нодных блокировок (NPVPN-1456).
    Единственный writer — review_bs_nodes; period: 'day'|'month' (диагностика)."""

    __tablename__ = "node_user_blocks"
    __table_args__ = (UniqueConstraint("node_id", "user_id", name="uq_node_user_blocks"),)

    id = Column(Integer, primary_key=True)
    node_id = Column(Integer, ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(8), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class NodeUsage(Base):
    __tablename__ = "node_usages"
    __table_args__ = (UniqueConstraint("created_at", "node_id"),)

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, unique=False, nullable=False)  # one hour per record
    node_id = Column(Integer, ForeignKey("nodes.id"))
    node = relationship("Node", back_populates="usages")
    uplink = Column(BigInteger, default=0)
    downlink = Column(BigInteger, default=0)


class NotificationReminder(Base):
    __tablename__ = "notification_reminders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="notification_reminders")
    type = Column(Enum(ReminderType), nullable=False)
    threshold = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
