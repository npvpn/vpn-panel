"""Возврат освобождённой памяти операционной системе (NPVPN-2120).

На каждую волну переподключения нод панель материализует полный конфиг со всеми
юзерами, а затем — по копии на ноду. Питон эту память освобождает, но glibc держит
её в своих аренах и ядру не отдаёт: на opl (27k юзеров, 172 ноды) RSS уходил с
медианных 1.5 ГБ до 5.7 ГБ при 7.9 ГБ памяти хоста. Дальше хост уходил в
swap-thrashing — ssh и Grafana не отвечали, при этом панель отвечала, и внешние
пробы доступности молчали.

malloc_trim(0) отдаёт свободные блоки ядру. Вызов проходит по аренам и берёт их
локи, поэтому его место — сразу после заведомо тяжёлой операции (волна конфигов),
а не на горячем пути запроса.

Функция специфична для glibc: на musl (alpine) её нет. Отсутствие — не ошибка,
просто возврат памяти не состоится, поэтому резолв мягкий и одноразовый.
"""

import ctypes

from app import logger

_resolved = False
_malloc_trim = None


def _resolve():
    """Найти malloc_trim в libc. Результат (в том числе отрицательный) кэшируется."""
    global _resolved, _malloc_trim

    if _resolved:
        return _malloc_trim

    _resolved = True
    try:
        libc = ctypes.CDLL("libc.so.6")
        _malloc_trim = libc.malloc_trim
        _malloc_trim.argtypes = [ctypes.c_size_t]
        _malloc_trim.restype = ctypes.c_int
    except (OSError, AttributeError) as exc:
        # Не glibc — живём без возврата памяти, но и не шумим на каждой волне.
        logger.info(f"[memory] malloc_trim unavailable ({type(exc).__name__}: {exc}); skipping trim")
        _malloc_trim = None

    return _malloc_trim


def trim_malloc() -> bool:
    """Вернуть свободные блоки glibc ядру.

    True — память ядру отдана; False — отдавать было нечего либо malloc_trim
    недоступен. Ошибки не пробрасываются: это уборка, а не бизнес-операция, и
    падать на ней джоба здоровья нод не должна.
    """
    trim = _resolve()
    if trim is None:
        return False

    try:
        return bool(trim(0))
    except Exception as exc:
        logger.warning(f"[memory] malloc_trim failed: {type(exc).__name__}: {exc}")
        return False
