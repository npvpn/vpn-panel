"""backfill empty v2ray documents from the file template

Revision ID: 7c2f4a8e1b6d
Revises: 4e2020eb3502
Create Date: 2026-09-23 11:10:00.000000

NPVPN-2096: миграция 6f9ee5710f34 оставляла новые документы пустыми, если старый
DB-параметр sub_v2ray_json_template не был задан. Подписки продолжали читать
смонтированный app/templates/v2ray/default.json как runtime-фолбэк, но в редакторе
панели конфиг не отображался. Материализуем этот фактический конфиг в БД.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

import sqlalchemy as sa
from alembic import op


revision = "7c2f4a8e1b6d"
down_revision = "4e2020eb3502"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

SOURCE_AUTHOR = "migration"
SOURCE_COMMENT = "перенос из настроек панели"
BACKFILL_COMMENT = "перенос файлового v2ray-конфига в БД"
TARGET_SLUGS = ("default", "bs")


def _file_template_body() -> str:
    """Вернуть именно тот шаблон, который до переноса использовал runtime."""
    from app.templates import render_template
    from config import V2RAY_SUBSCRIPTION_TEMPLATE

    return render_template(V2RAY_SUBSCRIPTION_TEMPLATE)


def _safe_file_template_body() -> str | None:
    try:
        body = _file_template_body()
        parsed = json.loads(body)
    except Exception as exc:  # noqa: BLE001 — ошибка файла не должна останавливать релиз
        logger.warning("NPVPN-2096: не удалось перенести файловый v2ray-конфиг в БД: %s", exc)
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "NPVPN-2096: файловый v2ray-конфиг должен быть JSON-объектом, получен %s",
            type(parsed).__name__,
        )
        return None
    return body


def _backfill(conn) -> None:
    """Дополнить только untouched-пустые документы исходной миграции.

    Более поздняя версия, даже пустая, является выбором администратора и не должна
    быть затёрта релизом.
    """
    body = _safe_file_template_body()
    if body is None:
        return

    rows = conn.execute(
        sa.text(
            "SELECT t.id, t.slug, v.version, v.body, v.comment, v.author_username "
            "FROM xray_templates t "
            "JOIN xray_template_versions v ON v.template_id = t.id "
            "JOIN ("
            "  SELECT template_id, MAX(version) AS max_version "
            "  FROM xray_template_versions GROUP BY template_id"
            ") latest ON latest.template_id = v.template_id AND latest.max_version = v.version "
            "WHERE t.slug IN (:default_slug, :bs_slug)"
        ),
        {"default_slug": TARGET_SLUGS[0], "bs_slug": TARGET_SLUGS[1]},
    ).fetchall()

    now = datetime.utcnow()
    insert = sa.text(
        "INSERT INTO xray_template_versions "
        "(template_id, version, body, comment, author_admin_id, author_username, created_at) "
        "VALUES (:template_id, :version, :body, :comment, NULL, :author, :created_at)"
    )
    for template_id, slug, version, current_body, comment, author in rows:
        if (
            version != 1
            or (current_body or "").strip()
            or comment != SOURCE_COMMENT
            or author != SOURCE_AUTHOR
        ):
            continue
        conn.execute(
            insert,
            {
                "template_id": template_id,
                "version": 2,
                "body": body,
                "comment": BACKFILL_COMMENT,
                "author": SOURCE_AUTHOR,
                "created_at": now,
            },
        )
        logger.info("NPVPN-2096: файловый v2ray-конфиг перенесён в документ %s", slug)


def _rollback(conn) -> None:
    conn.execute(
        sa.text(
            "DELETE FROM xray_template_versions "
            "WHERE version = 2 AND author_username = :author AND comment = :comment"
        ),
        {"author": SOURCE_AUTHOR, "comment": BACKFILL_COMMENT},
    )


def upgrade() -> None:
    _backfill(op.get_bind())


def downgrade() -> None:
    _rollback(op.get_bind())
