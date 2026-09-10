# Конвенция: как добавлять общие правила и скиллы

Правило работает одновременно в Cursor и Claude через схему «один источник + тонкие обёртки»: полнотекст в `docs/`, выжимки с ссылками в `.claude/skills/` и `.cursor/rules/`.

Кратко:

- Полнотекст живёт в `docs/conventions/<topic>.md`, обёртки ссылаются на него.
- Обёртка для Claude — `.claude/skills/<topic>/SKILL.md` с описанием-триггером.
- Обёртка для Cursor — `.cursor/rules/<topic>.mdc` с `description`, `globs`, `alwaysApply`.
- Always-on правило дублируется в `CLAUDE.md` и `.cursor/rules/00-project.mdc`.

Полные правила — в репозитории бота:
`telegram_bot/docs/conventions/authoring-rules.md`.
