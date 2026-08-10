import glob
import importlib.util
import os


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_per_bot_managed_settings.py"))
    assert len(matches) == 1, f"expected exactly one per-bot managed settings migration, got {matches}"
    spec = importlib.util.spec_from_file_location("per_bot_managed_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_upgrade_and_downgrade():
    module = _load_migration()
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")
    assert module.down_revision == "9b1d29ea4018"
