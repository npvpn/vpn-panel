"""Суточный снимок состава хостов (NPVPN-2072).

Нужен, чтобы восстановить задним числом, какие ноды и адреса стояли за хостом в
конкретный день — без этого «какие ноды были у юзера в дату X» не ответить: снимки
весов уже дают вес ноды на дату, но не список нод/адресов, из которых собирался
хост, а состав хоста меняется (привязка нод, их статус/адрес, статическая строка
host.address) чаще, чем хотелось бы держать в голове.

Источник состава — не кэш `xray.hosts`, а прямой запрос к БД с теми же чистыми
функциями `resolve_host_addresses`/`resolve_host_node_ids`, что строят этот кэш
(см. app/xray/__init__.py:hosts). Причина: `xray.hosts` — это dict, ключ которого
inbound_tag, а внутри — список словарей БЕЗ host_id (см. форму записи там же), так
что обратное сопоставление "запись кэша -> host_id" пришлось бы делать по позиции
в списке, а это ломается при любом рассинхроне порядка между временем сборки кэша
и временем работы джобы. Прямой запрос к ProxyHost и вызов тех же resolve_*
функций поверх свежих ORM-объектов даёт БАЙТ-В-БАЙТ тот же результат, что дал бы
кэш, если бы его сейчас пересобрали — а он и пересобирается на каждую мутацию
хостов/нод (routers/*.py дергают xray.hosts.update()), так что расхождение между
"текущим кэшем" и "текущей БД" не является устойчивым состоянием: обычная работа
приложения его не допускает. Собственно копии кэша это не создаёт: используются
ровно те же resolve_host_addresses/resolve_host_node_ids, что и кэш.
"""

import time
from datetime import UTC, datetime

from sqlalchemy.orm import selectinload

from app import logger, scheduler
from app.db import GetDB, crud
from app.db.models import ProxyHost
from app.subscription.address_context_builder import day_index
from app.xray.address_policy import ARCHIVE_RETENTION_DAYS
from app.xray.host_addresses import resolve_host_addresses, resolve_host_node_ids
from config import JOB_SNAPSHOT_HOST_COMPOSITION_INTERVAL

# Тот же горизонт, что и у остального архива журнала NPVPN-2072 (M4) — единый
# источник в app/xray/address_policy.py, не отдельное число.
RETENTION_DAYS = ARCHIVE_RETENTION_DAYS


def _host_payload(host: ProxyHost) -> list[dict]:
    """[{"node_id", "address"}, ...] в порядке выдачи.

    Когда адреса приходят от нод (host.address пуст), resolve_host_addresses и
    resolve_host_node_ids построены на одном и том же множестве нод в одном и том
    же порядке (см. host_addresses.visible_nodes) — zip корректно спаривает их.

    Когда адрес статический (host.address задан, обычно маскировка под домен),
    соответствия "адрес <-> нода" нет по построению: одна строка адреса может
    стоять за произвольным числом привязанных нод (см. комментарий в
    AddressContext.pick про это же несоответствие). node_id в этом случае
    записываем как None — врать здесь конкретной нодой было бы хуже, чем не
    указывать её вовсе.
    """
    addresses = resolve_host_addresses(host)
    if host.address:
        return [{"node_id": None, "address": address} for address in addresses]
    node_ids = resolve_host_node_ids(host)
    return [{"node_id": node_id, "address": address} for node_id, address in zip(node_ids, addresses, strict=True)]


def snapshot_host_composition() -> None:
    t0 = time.monotonic()
    epoch = day_index(datetime.now(UTC))

    with GetDB() as db:
        # selectinload: host.nodes — коллекция без eager-загрузки по умолчанию,
        # без неё _host_payload бьёт по БД за нодами отдельным SELECT на каждый
        # хост (N+1) в джобе, которая крутится каждый час (NPVPN-2072).
        hosts = (
            db.query(ProxyHost).options(selectinload(ProxyHost.nodes)).filter(ProxyHost.is_disabled.isnot(True)).all()
        )
        for host in hosts:
            crud.write_host_composition_snapshot(db, epoch, host.id, _host_payload(host))

        # write_host_composition_snapshot сама не коммитит — коммитим здесь, один
        # раз на весь проход (десятки хостов), а не по одному на хост. КОММИТ
        # ЗДЕСЬ, А НЕ В prune: подчистка — отдельная по смыслу обязанность (и может
        # начать жить своим расписанием), падение в ней не должно откатывать уже
        # состоявшуюся запись снимков (NPVPN-2072).
        db.commit()

        crud.prune_host_composition_snapshots(db, epoch, RETENTION_DAYS)

    logger.info(f"[snapshot_host_composition] done hosts={len(hosts)} epoch={epoch} dt={time.monotonic() - t0:.2f}s")


scheduler.add_job(
    snapshot_host_composition,
    "interval",
    seconds=JOB_SNAPSHOT_HOST_COMPOSITION_INTERVAL,
    coalesce=True,
    max_instances=1,
)
