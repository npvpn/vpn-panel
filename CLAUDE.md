# panel — форк Marzban (NPVPN)

Панель — форк [Marzban](https://github.com/Gozargah/Marzban), живущий в общем
рабочем контуре с ботом `telegram_bot/`. Обратно в upstream не вливается:
«минимальный дифф» не является ценностью, рефакторинг затронутого кода —
норма.

Основной документ — [`docs/architecture.md`](docs/architecture.md): слои,
зависимости и сквозные инварианты (MySQL-специфика, alembic панели, ноды и
xray). Читать его перед правками в `app/`.

## Как собирать и запускать

Команды `docker compose` (build/up/logs/exec) запускаются из каталога бота
`telegram_bot/`, не отсюда — сборка образа `marzban` идёт из исходников этого
репозитория через `telegram_bot/docker-compose.override.yml`.

## Конвенции

Общие конвенции разработки (коммиты, PR, тесты, git flow) живут в
репозитории бота: `telegram_bot/docs/conventions/`. В этом репозитории —
короткие указатели на них в [`docs/conventions/`](docs/conventions/), по
образцу существующего [`docs/releases.md`](docs/releases.md).
