import pytest

from app.xray.address_policy import (
    EXHAUSTED_WEIGHT,
    epoch_for,
    epoch_start_day,
    pick_keys,
)


def candidates(n, weight=100.0):
    return [(i, weight) for i in range(1, n + 1)]


def test_determinism():
    first = pick_keys(42, candidates(6), 2, 0)
    second = pick_keys(42, candidates(6), 2, 0)
    assert first == second
    assert len(first) == 2


def test_returns_all_when_fewer_than_n():
    assert pick_keys(42, candidates(2), 5, 0) == [1, 2]


def test_never_empty_when_all_weights_zero():
    zero = [(i, 0.0) for i in range(1, 6)]
    assert len(pick_keys(42, zero, 2, 0)) == 2


def test_exhausted_node_loses_to_healthy_one():
    """Исчерпанная нода выдаётся, только если иначе не набрать N."""
    mixed = [(1, 0.0), (2, 0.0), (3, 1_000_000.0), (4, 1_000_000.0)]
    picked = set(pick_keys(42, mixed, 2, 0))
    assert picked == {3, 4}


def test_weighting_is_proportional():
    """Нода с вдвое большим остатком набирает примерно вдвое больше юзеров."""
    pool = [(1, 200.0), (2, 100.0), (3, 100.0), (4, 100.0)]
    counts = {1: 0, 2: 0, 3: 0, 4: 0}
    for user_id in range(4000):
        for key in pick_keys(user_id, pool, 1, 0):
            counts[key] += 1
    assert counts[1] > 1.5 * counts[2]
    assert counts[1] < 2.6 * counts[2]


def test_stability_on_node_addition():
    """Добавление ноды переставляет малую долю юзеров, а не всех."""
    before = [(i, 100.0) for i in range(1, 7)]
    after = before + [(7, 100.0)]
    moved = 0
    total = 2000
    for user_id in range(total):
        if set(pick_keys(user_id, before, 2, 0)) != set(pick_keys(user_id, after, 2, 0)):
            moved += 1
    assert moved < total * 0.45


def test_epoch_changes_selection():
    pool = candidates(8)
    assert pick_keys(42, pool, 2, 0) != pick_keys(42, pool, 5, 0)


def test_manual_offset_changes_selection_immediately():
    assert epoch_for(42, day_index=100, period_days=2, offset=0) != epoch_for(
        42, day_index=100, period_days=2, offset=1
    )


def test_rotation_is_smeared_across_users():
    """Юзеры меняют эпоху в разные сутки, а не все одномоментно."""
    period = 4
    flip_days = set()
    for user_id in range(200):
        for day in range(period):
            if epoch_for(user_id, day, period, 0) != epoch_for(user_id, day + 1, period, 0):
                flip_days.add(day)
    assert len(flip_days) == period


def test_epoch_start_day_is_within_period():
    for user_id in range(50):
        for day in range(20):
            start = epoch_start_day(user_id, day, period_days=3)
            assert 0 <= day - start < 3


def test_period_days_below_one_is_clamped():
    assert epoch_for(1, 10, 0, 0) == epoch_for(1, 10, 1, 0)


@pytest.mark.parametrize("n", [0, -1])
def test_non_positive_n_returns_empty(n):
    assert pick_keys(42, candidates(5), n, 0) == []


def test_exhausted_weight_is_positive():
    assert EXHAUSTED_WEIGHT > 0


def test_node_is_exhausted_at_and_above_cutoff():
    """Порог — «достигла», а не «превысила»: ровно 90% уже выбывает (NPVPN-2072)."""
    from app.xray.address_policy import is_exhausted

    assert is_exhausted(used=89, limit=100, cutoff_percent=90) is False
    assert is_exhausted(used=90, limit=100, cutoff_percent=90) is True
    assert is_exhausted(used=91, limit=100, cutoff_percent=90) is True


def test_node_without_limit_is_never_exhausted():
    """Незаполненный лимит не делает ноду невидимой — судить не по чему."""
    from app.xray.address_policy import is_exhausted

    assert is_exhausted(used=10**15, limit=None, cutoff_percent=90) is False
    assert is_exhausted(used=10**15, limit=0, cutoff_percent=90) is False


def test_node_without_usage_is_never_exhausted():
    """Данных о расходе нет (скрипт не доехал) — нода остаётся в выдаче."""
    from app.xray.address_policy import is_exhausted

    assert is_exhausted(used=None, limit=100, cutoff_percent=90) is False


def test_cutoff_percent_out_of_range_falls_back_to_full_limit():
    """Мусорный порог не должен выкашивать парк нод целиком."""
    from app.xray.address_policy import is_exhausted

    assert is_exhausted(used=50, limit=100, cutoff_percent=0) is False
    assert is_exhausted(used=99, limit=100, cutoff_percent=-5) is False
    assert is_exhausted(used=99, limit=100, cutoff_percent=1000) is False
    assert is_exhausted(used=100, limit=100, cutoff_percent=1000) is True
