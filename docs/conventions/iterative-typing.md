# Конвенция: итеративная типизация и снятие type: ignore

Долг типов заморожен в `mypy-baseline.txt`. Цель — baseline только уменьшается, новый код типизирован с самого начала.

Кратко:

- `mypy-baseline.txt` в PR может только уменьшаться. Рост → возврат на доработку.
- Новый код без `# type: ignore` и без strict ruff-нарушений.
- Снимаем долг модуль за модулем: правим типы, обновляем baseline (`uv run mypy app | uv run mypy-baseline sync`).
- mypy «new errors» чиним в коде, не `sync` — расширять baseline запрещено.

Полные правила — в репозитории бота:
`telegram_bot/docs/conventions/iterative-typing.md`.
