"""Выбор подмножества нод/адресов хоста для конкретного юзера (NPVPN-2072).

Чистый модуль (без импортов БД/xray) — юнит-тестируется в песочнице tests/conftest.py,
как bs_limit / bs_context.

Взвешенный rendezvous-хеш, а не «хеш по модулю числа нод»: при добавлении или удалении
ноды переезжает лишь доля назначений, пропорциональная изменению, тогда как модуль
переставлял бы всех при каждом движении парка нод.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Hashable, Sequence

_DIGEST_BYTES = 8
_HASH_SPACE = 2 ** (8 * _DIGEST_BYTES)

# Вес исчерпанной ноды. Не ноль: инвариант «подписка никогда не остаётся без адресов»
# важнее экономии трафика — перерасход лучше неработающего VPN. Реальные веса измеряются
# в байтах, поэтому единица гарантированно проигрывает любой живой ноде.
EXHAUSTED_WEIGHT = 1.0


def _unit_hash(*parts: object) -> float:
    """Детерминированное число в (0, 1] из произвольных частей ключа."""
    raw = ":".join(str(part) for part in parts).encode()
    digest = hashlib.blake2b(raw, digest_size=_DIGEST_BYTES).digest()
    # +1 в числителе исключает 0: ln(0) не определён.
    return (int.from_bytes(digest, "big") + 1) / (_HASH_SPACE + 1)


def _score(user_id: int, key: Hashable, epoch: int, weight: float) -> float:
    """Взвешенный rendezvous-score. Больше — выше в выдаче."""
    u = _unit_hash(user_id, key, epoch)
    if u >= 1.0:
        # Верхняя граница достижима при (value + 1) == (_HASH_SPACE + 1); ln(1) == 0.
        u = 1.0 - 1e-12
    return max(weight, EXHAUSTED_WEIGHT) / -math.log(u)


def pick_keys(
    user_id: int,
    candidates: Sequence[tuple[Hashable, float]],
    n: int,
    epoch: int,
) -> list[Hashable]:
    """N ключей из candidates для этого юзера, пропорционально весам.

    candidates — пары (ключ, вес). Ключом может быть node_id или сам адрес: для
    легаси-хостов со статическим host.address соответствия «адрес ↔ нода» нет,
    и выбор идёт по строке адреса с равными весами.

    Порядок результата следует порядку candidates — вызывающий код рассчитывает
    на сохранение исходной последовательности адресов.
    """
    if n <= 0 or not candidates:
        return []
    if len(candidates) <= n:
        return [key for key, _ in candidates]
    ranked = sorted(
        candidates,
        # Вторым ключом — строковое представление: при равных score порядок обязан
        # быть детерминированным, иначе подписка «дышала» бы между рендерами.
        key=lambda item: (-_score(user_id, item[0], epoch, item[1]), str(item[0])),
    )
    chosen = {key for key, _ in ranked[:n]}
    return [key for key, _ in candidates if key in chosen]


def _smear(user_id: int, period_days: int) -> int:
    """Сдвиг эпохи, размазывающий ротацию по суткам внутри периода.

    Без него вся база меняла бы IP одномоментно раз в period_days: все клиенты
    переподключаются, ноды получают волну, и любая ошибка проявляется у всех сразу.
    """
    return int(_unit_hash("smear", user_id) * period_days) % period_days


def epoch_for(user_id: int, day_index: int, period_days: int, offset: int) -> int:
    """Номер эпохи юзера. offset — ручная ротация (users.address_rotation_offset)."""
    period = max(1, period_days)
    return (day_index + _smear(user_id, period)) // period + offset


def epoch_start_day(user_id: int, day_index: int, period_days: int) -> int:
    """Сутки, в которые началась текущая эпоха юзера.

    По ним выбирается снимок весов: вес обязан быть постоянным внутри эпохи, иначе
    подмножество поплывёт и у юзера начнут скакать IP.
    """
    period = max(1, period_days)
    smear = _smear(user_id, period)
    return (day_index + smear) // period * period - smear
