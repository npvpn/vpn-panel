import glob
import importlib.util
import os


def _load_migration():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    matches = glob.glob(os.path.join(here, "app/db/migrations/versions/*_npvpn_1768_bs_extra_period.py"))
    assert len(matches) == 1, f"expected exactly one bs_extra_period migration, got {matches}"
    spec = importlib.util.spec_from_file_location("bs_extra_period_migration", matches[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_has_upgrade_and_downgrade():
    module = _load_migration()
    assert hasattr(module, "upgrade")
    assert hasattr(module, "downgrade")
    assert module.down_revision is not None
