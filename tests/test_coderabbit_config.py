"""Тесты конфигурации CodeRabbit для панели.

Отличие от бота: общие конвенции подключаются кросс-репными записями
`npvpn/telegram_bot:...`. Локальные пути проверяются на существование,
кросс-репные — на форму: опечатка в имени репозитория молча лишает
ревьюера всех общих правил.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".coderabbit.yaml"

BOT_REPO = "npvpn/telegram_bot"


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _file_pattern_values(patterns: list) -> list[str]:
    values: list[str] = []
    for entry in patterns:
        raw = entry["files"] if isinstance(entry, dict) else entry
        values.extend(part.strip() for part in raw.split(",") if part.strip())
    return values


def test_config_is_valid_yaml():
    assert CONFIG.is_file(), ".coderabbit.yaml отсутствует"
    assert isinstance(_config(), dict)


def test_review_mode_matches_spec():
    cfg = _config()
    reviews = cfg["reviews"]
    assert cfg["language"] == "ru"
    assert reviews["profile"] == "chill"
    assert reviews["request_changes_workflow"] is False
    assert reviews["auto_assign_reviewers"] is False
    assert reviews["auto_review"]["enabled"] is True
    assert reviews["auto_review"]["drafts"] is False


def test_noise_sources_are_disabled():
    reviews = _config()["reviews"]
    assert reviews["poem"] is False
    assert reviews["in_progress_fortune"] is False
    assert reviews["tools"]["ruff"]["enabled"] is False


def test_finishing_touches_disabled():
    touches = _config()["reviews"]["finishing_touches"]
    enabled = [name for name, value in touches.items() if value.get("enabled")]
    assert not enabled, f"finishing_touches включены: {enabled}"


def test_learnings_scope_is_local():
    assert _config()["knowledge_base"]["learnings"]["scope"] == "local"


def test_local_guideline_patterns_resolve():
    patterns = _file_pattern_values(_config()["knowledge_base"]["code_guidelines"]["filePatterns"])
    dangling = [p for p in patterns if ":" not in p and not list(REPO_ROOT.glob(p))]
    assert not dangling, f"локальные filePatterns указывают в никуда: {dangling}"


def test_shared_conventions_come_from_the_bot_repo():
    """Общие правила не копируются в панель — они читаются из репо бота."""
    patterns = _file_pattern_values(_config()["knowledge_base"]["code_guidelines"]["filePatterns"])
    cross_repo = [p for p in patterns if p.startswith(f"{BOT_REPO}:")]
    assert cross_repo, "нет кросс-репных ссылок на конвенции бота"
    assert any("docs/conventions/" in p for p in cross_repo)


def test_path_instructions_match_existing_paths():
    instructions = _config()["reviews"]["path_instructions"]
    assert instructions, "path_instructions пуст"
    dangling = [item["path"] for item in instructions if not list(REPO_ROOT.glob(item["path"]))]
    assert not dangling, f"path_instructions не совпадают ни с одним файлом: {dangling}"


def test_path_instructions_guard_architecture_freshness():
    instructions = _config()["reviews"]["path_instructions"]
    guarded = {item["path"] for item in instructions if "docs/architecture.md" in item["instructions"]}
    assert "app/db/models.py" in guarded
