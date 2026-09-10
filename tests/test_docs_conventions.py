"""Тесты указателей на общие конвенции.

Полнотекст общих правил живёт в репозитории бота. Здесь — короткие
указатели: копия правила разошлась бы с источником, а её отсутствие
оставило бы человека без карты.
"""

from pathlib import Path

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
