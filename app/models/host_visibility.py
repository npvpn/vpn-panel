"""Значения `hosts.visibility` (NPVPN-2044).

Листовой модуль без зависимостей: константы нужны и `app/db/models.py`, и
`app/models/proxy.py`, а между ними уже есть импорт в одну сторону
(`db.models` → `models.proxy`), поэтому держать их в любом из двух файлов
значило бы замкнуть цикл.
"""

#: Хост виден всем ботам своей панели и не тарифицируется.
HOST_VISIBILITY_SHARED = "shared"
#: Хост виден только привязанным ботам. Дефолт: новый хост не уходит всем молча.
HOST_VISIBILITY_RESTRICTED = "restricted"

HOST_VISIBILITY_VALUES = (HOST_VISIBILITY_SHARED, HOST_VISIBILITY_RESTRICTED)
