"""Тесты документа архитектуры панели.

Документ — вход AI-ревьюера. Панель специфична (форк Marzban, MySQL,
свой alembic), и ни один общий документ бота этого не описывает.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"

REQUIRED_SECTIONS = (
    "## Что это за репозиторий",
    "## Слои и зависимости",
    "## Сквозные инварианты",
    "## Ноды и xray",
)

REQUIRED_INVARIANTS = (
    "utf8mb4_bin",
    "INT32",
    "alembic",
    "threadpool",
)

MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_architecture_document_exists():
    assert ARCHITECTURE.is_file(), "docs/architecture.md отсутствует"


def test_architecture_has_required_sections():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    assert not missing, f"нет обязательных разделов: {missing}"


def test_architecture_names_panel_specific_invariants():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    missing = [i for i in REQUIRED_INVARIANTS if i not in text]
    assert not missing, f"не описана специфика панели: {missing}"


def test_architecture_states_fork_is_not_upstreamed():
    """Ключевое следствие: «минимальный дифф» здесь не ценность."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    assert "не вливается" in text


def test_architecture_relative_links_resolve():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    broken = []
    for target in MARKDOWN_LINK.findall(text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = (ARCHITECTURE.parent / target.split("#", 1)[0]).resolve()
        if not path.exists():
            broken.append(target)
    assert not broken, f"битые относительные ссылки: {broken}"


def test_claude_md_exists_and_points_at_architecture():
    claude = REPO_ROOT / "CLAUDE.md"
    assert claude.is_file(), "CLAUDE.md панели отсутствует"
    assert "docs/architecture.md" in claude.read_text(encoding="utf-8")
