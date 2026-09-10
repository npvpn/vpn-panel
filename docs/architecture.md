# Архитектура панели NPVPN

Документ описывает то, что не восстанавливается чтением одного файла:
межмодульные связи, сквозные инварианты и грабли. Пересказ того, что и так
видно в коде, сюда не идёт — он устаревает первым и обесценивает документ.

Это входной контекст для AI-ревьюера PR (CodeRabbit, `.coderabbit.yaml`
репозитория бота, `knowledge_base.code_guidelines.filePatterns`), а не
документ для людей в чистом виде.

## Что это за репозиторий

Панель — **форк [Marzban](https://github.com/Gozargah/Marzban), который
обратно в upstream не вливается**. Прямое следствие: «минимальный дифф» не
является ценностью. Рефакторинг затронутого кода — норма, а не повод для
замечания «слишком большой diff»; логика выносится из роутеров (`app/routers/`)
в сервисы (`app/services/`), а не копируется по месту рядом со старым кодом.

Панель живёт в общем рабочем контуре с ботом (`telegram_bot/`). Она не
собирается и не поднимается из своего каталога — образ `marzban` собирается
из исходников `../panel` контекстом в `telegram_bot/docker-compose.override.yml`,
и команды `docker compose build marzban` / `docker compose up` запускаются
из каталога бота, а не отсюда.

## Слои и зависимости

- `main.py` — uvicorn entrypoint (`main:app`), просто запускает приложение,
  собранное в `app/__init__.py`.
- `app/` — FastAPI-приложение:
  - `routers/` — HTTP-хендлеры (admin, bot, core, home, node, settings,
    subscription, system, user, user_template, managed, memory);
  - `services/` — бизнес-логика (панельные настройки, managed-настройки,
    client apps, дайджест пользователей);
  - `db/` — модели (`models.py`), CRUD (`crud.py`) и собственный alembic
    (`db/migrations/`);
  - `dashboard/` — фронтенд админки (отдельная сборка, node_modules/dist);
  - `jobs/` — периодические задачи (учёт трафика, ревью пользователей и
    BS-нод, снятие просроченных, сброс счётчика трафика пользователей
    (`reset_user_data_usage`), уведомления, пуш xray-конфига);
  - `xray/` — работа с нодами и xray-конфигом (`config.py`, `node.py`,
    `node_config.py`, `operations.py`, каскад ролей, BS-роутинг/лимиты);
  - `telegram/` — уведомления через Telegram (не путать с ботом NPVPN —
    это встроенный в панель Marzban telegram-модуль);
  - `subscription/` — генерация подписочных ссылок и форматов (v2ray,
    clash, singbox, outline и т.д.).
- `config.py` — переменные окружения (`decouple.config`), в т.ч.
  `SQLALCHEMY_DATABASE_URL`, `UVICORN_*`, фичефлаги вроде
  `MEMORY_PROFILING_ENABLED`.

Свой alembic внутри `app/db/migrations/` (`alembic.ini`:
`script_location = app/db/migrations`) — отдельная цепочка ревизий,
независимая от `telegram_bot/src/alembic/`. Миграции панели создаются только
через `alembic revision` в этом репозитории; не смешивать с миграциями бота
и не переносить модели между ними вручную.

## Сквозные инварианты

Каждый инвариант ниже — готовое правило ревью: нарушение почти всегда
означает баг, а не осознанное исключение.

### MySQL, а не Postgres — collation `utf8mb4_bin` на FK к `inbounds.tag`

БД панели — MySQL (`nvb_mysql` в контуре бота), а не Postgres, как у бота.
Внешний ключ на `inbounds.tag` требует явного `collation="utf8mb4_bin"` на
стороне FK-колонки — без этого на MySQL миграция может упасть или завести
рассинхрон с `inbounds.tag` (см. `app/db/migrations/versions/5a20cee1a4e9_*`,
`2c0cafb40725_*`, `a98d3011a530_*`, `c1a7e4b9d2f3_*`,
`dd725e4d3628_fix_mysql_collations.py`). Тест миграции на sqlite это не
ловит — sqlite не проверяет collation FK так, как MySQL, поэтому новая
миграция с FK на `inbounds.tag` должна явно выставлять `utf8mb4_bin` и не
полагаться на зелёный sqlite-прогон как на достаточное подтверждение.

### `users.expire` — `BigInteger`, не `Integer`: потолок `INT32`

`User.expire` (и парный `UserTemplate.expire`) — намеренно `BigInteger`, а не
`Integer`. В MySQL `Integer` — это `INT` с диапазоном до `2147483647`
(2038-01-19 03:14:07 UTC). Бессрочные подписки бота выставляют именно этот
UNIX-потолок как «бесконечность», и любое продление поверх него на `Integer`
роняло `UPDATE` ошибкой `Out of range value for column 'expire'` (NPVPN-1879).
Правило ревью: `expire`-подобная колонка, хранящая unix-timestamp, не должна
объявляться как `Integer` — ни в новой таблице, ни при правке существующей.

### Naive `datetime` — локальное время процесса, хосты в UTC

Как и в боте, naive `datetime` (без `tzinfo`, `datetime.utcnow()` в
`app/db/models.py`) трактуется как локальное время процесса. Продовые
сервера живут в UTC, поэтому сравнение naive-значений из БД с
`datetime.now(UTC)` — источник трудноуловимых расхождений при сверке
(см. также историю дрейфа `expire` при смене таймзоны хоста).

## Ноды и xray

Панель управляет флотом xray-нод: пушит на них конфиг, собранный из
Core settings (`xray_config.json`) плюс пользователей из БД плюс каскадные
добавки по роли ноды (entry/exit/direct, см.
[`cascade-node-roles.md`](cascade-node-roles.md)). Сборка
пользовательской части конфига идёт через `include_db_users()`
(`app/xray/config.py`) — она добавляет к каталожным инбаундам активных
пользователей и кэширует сериализованный per-нодный JSON
(`app/xray/node_config.py`), чтобы не пересобирать его на каждый пуш.

Ключевая ловушка — два разных пути для одного и того же сетевого
sync-вызова к нодам, и они изолированы не одинаково:

- **Защищённый путь.** Реальный сетевой I/O к нодам (gRPC-вызовы xray API)
  идёт через выделенный пул `_xray_executor`
  (`app/utils/concurrency.py`: `ThreadPoolExecutor(thread_name_prefix="xray-pool")`,
  размер — `XRAY_THREAD_POOL_SIZE`), заведённый отдельно от Starlette именно
  для того, чтобы xray-вызовы не делили пул с обработкой HTTP-запросов.
  Попасть в него можно декоратором `@threaded_function` (на функциях
  нижнего уровня — `_add_user_to_inbound`, `_remove_user_from_inbound`,
  `_alter_inbound_user`, `connect_node`, `restart_node` в
  `app/xray/operations.py`) либо прямым `get_xray_executor().submit(...)`,
  как делают джобы (`app/jobs/review_users.py`, `app/jobs/record_usages.py`).
- **Незащищённый путь.** Функции верхнего уровня `add_user`, `remove_user`,
  `update_user` (`app/xray/operations.py`) сами `@threaded_function` не
  помечены — внутри они лишь fire-and-forget раскладывают сетевые вызовы по
  `_xray_executor` через декорированные хелперы, не дожидаясь результата. Но
  из `app/routers/user.py` эти функции целиком планируются через
  `bg.add_task(xray.operations.add_user, ...)` (аналогично для
  `remove_user`/`update_user`) — а `BackgroundTasks` Starlette прогоняет
  sync-колбэк через `run_in_threadpool`, то есть через тот же anyio-пул,
  на котором висят обычные sync-хендлеры. Именно на этом пути уже случалось
  залипание панели: до появления `_get_ready_nodes()` (кэш готовности нод
  только по локальным флагам, без сети) выбор готовых нод шёл через сетевые
  свойства `node.connected`/`node.started`, которые синхронно били по
  каждой ноде и сериализовали вызывающего — одна медленная нода среди ~200
  стопорила этот общий threadpool. Конкретный вызов уже зафиксирован, но
  сам путь диспетчеризации (`bg.add_task` → общий пул) остался, и новый
  синхронный сетевой вызов, добавленный внутри
  `add_user`/`remove_user`/`update_user` в обход `_xray_executor`, повторит
  ту же проблему.

Правило ревью: новый синхронный сетевой вызов к ноде (xray API, gRPC,
`node.connected`/`node.started` и подобные сетевые свойства) обязан идти
через `@threaded_function` или `get_xray_executor()`, а не выполняться
напрямую внутри функции, которую диспетчеризуют через `bg.add_task` из
роутера, — это тот же общий threadpool, что и у обычных HTTP-запросов.
Тяжёлые xray-операции вне запроса планировать по образцу
`app/jobs/review_users.py` (`executor.submit(xray.operations.remove_user, u)`
через `get_xray_executor()`), а не через `bg.add_task`.

## Смотри также

- [`cascade-node-roles.md`](cascade-node-roles.md) — устройство ролей нод
  (entry/exit/direct) и каскадной сборки конфига.
- [`logging.md`](logging.md) — стандарт логирования панели, env-переменные,
  правила для нового кода.
