"""Тесты указателей на общие конвенции.

Полнотекст общих правил живёт в репозитории бота. Здесь — короткие
указатели: копия правила разошлась бы с источником, а её отсутствие
оставило бы человека без карты.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONVENTIONS = REPO_ROOT / "docs" / "conventions"

EXPECTED = (
    "writing-tests",
    "structural-fixes",
    "commit-messages",
    "pull-requests",
    "iterative-typing",
    "yougile-updates",
    "authoring-rules",
    "fixing-ci",
)


def test_all_expected_pointers_exist():
    missing = [name for name in EXPECTED if not (CONVENTIONS / f"{name}.md").is_file()]
    assert not missing, f"нет указателей: {missing}"


def test_each_pointer_names_its_source_in_the_bot_repo():
    broken = []
    for name in EXPECTED:
        text = (CONVENTIONS / f"{name}.md").read_text(encoding="utf-8")
        if f"telegram_bot/docs/conventions/{name}.md" not in text:
            broken.append(name)
    assert not broken, f"указатели без ссылки на источник: {broken}"


def test_pointers_are_short():
    """Указатель — выжимка, а не копия: копия разойдётся с источником."""
    too_long = []
    for name in EXPECTED:
        lines = (CONVENTIONS / f"{name}.md").read_text(encoding="utf-8").splitlines()
        if len(lines) > 25:
            too_long.append((name, len(lines)))
    assert not too_long, f"указатели разрослись до копий: {too_long}"


def test_pointers_have_meaningful_content():
    """Указатель содержит выжимку, а не только заголовок и ссылку на источник.

    Тест проверяет, что в файле есть минимум 3 содержательные строки
    (непустые и не только пробелы) помимо заголовка и строки со ссылкой
    на источник. Это гарантирует, что указатель несёт информацию.
    """
    insufficient = []
    for name in EXPECTED:
        path = CONVENTIONS / f"{name}.md"
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        # Фильтруем: убираем пустые строки, заголовок (начинается на #),
        # и строку со ссылкой на источник (содержит telegram_bot/docs/conventions)
        content_lines = [
            line
            for line in lines
            if line.strip()  # непустая
            and not line.startswith("#")  # не заголовок
            and "telegram_bot/docs/conventions" not in line  # не ссылка на источник
        ]

        if len(content_lines) < 3:
            insufficient.append((name, len(content_lines), lines))

    assert not insufficient, f"указатели без выжимки: {[(name, cnt) for name, cnt, _ in insufficient]}"


def test_source_files_exist_if_bot_repo_available():
    """Проверка существования файлов-источников в репозитории бота.

    Тест условный: если репозиторий бота доступен рядом, проверяем что каждый
    указанный файл-источник существует (чтобы не пропустить переименование
    конвенции в боте и протухание указателей). Если соседнего бота нет
    (например, CI панели), тест пропускается — иначе он всегда падал бы
    в CI, ломая всю сборку за отсутствием соседнего репо.

    Путь до бота вычисляется относительно теста, не хардкодится абсолютный.
    """
    # Вычисляем путь: от панели (REPO_ROOT = parents[1] от теста = сама панель)
    # поднимаемся на один уровень (parents[0] = /home/kruptor/stuff/npvpn),
    # потом telegram_bot
    bot_root = REPO_ROOT.parents[0] / "telegram_bot"
    bot_conventions = bot_root / "docs" / "conventions"

    if not bot_conventions.exists():
        pytest.skip(f"репозиторий бота недоступен ({bot_conventions}), пропускаем проверку существования источников")

    missing_sources = []
    for name in EXPECTED:
        source_file = bot_conventions / f"{name}.md"
        if not source_file.is_file():
            missing_sources.append(name)

    # .coderabbit.yaml ссылается кросс-репно и на docs/git-flow.md бота
    # (не через указатель в docs/conventions/) — проверяем той же проверкой,
    # чтобы протухание этого источника тоже ловилось.
    if not (bot_root / "docs" / "git-flow.md").is_file():
        missing_sources.append("git-flow.md")

    assert not missing_sources, f"файлы-источники в боте не найдены: {missing_sources}"
