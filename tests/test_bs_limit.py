import copy

from app.xray.bs_limit import (
    aggregate_bs_usage,
    bs_counter_step,
    bs_stub_remark,
    carry_over_pool,
    diff_blocks,
    monthly_effective_limit,
    over_limit,
    over_limit_monthly_pool,
    period_keys,
    pick_bs_bar,
    strip_blocked_clients,
)


class FakeConfig(dict):
    def copy(self):
        return FakeConfig(copy.deepcopy(dict(self)))


def base():
    return FakeConfig(
        {
            "inbounds": [
                {
                    "tag": "VLESS_TCP",
                    "settings": {"clients": [{"email": "1.alice"}, {"email": "2.bob"}, {"email": "10.carol"}]},
                },
                {"tag": "NO_SETTINGS"},
            ],
        }
    )


def test_period_keys_formats_month():
    from datetime import datetime

    assert period_keys(datetime(2026, 6, 16, 13, 5)) == "2026-06"


def test_counter_step_fresh_row_starts_from_delta():
    r = bs_counter_step(None, 100, "2026-06")
    assert r == {"monthly_used": 100, "monthly_period": "2026-06"}


def test_counter_step_same_period_accumulates():
    existing = {"monthly_used": 500, "monthly_period": "2026-06"}
    r = bs_counter_step(existing, 30, "2026-06")
    assert r["monthly_used"] == 530


def test_counter_step_new_month_resets():
    existing = {"monthly_used": 500, "monthly_period": "2026-06"}
    r = bs_counter_step(existing, 30, "2026-07")
    assert r["monthly_used"] == 30 and r["monthly_period"] == "2026-07"


def test_diff_blocks_computes_to_block_and_to_unblock():
    desired = {(1, 10), (1, 11), (2, 10)}
    current = {(1, 11), (3, 99)}
    to_block, to_unblock = diff_blocks(desired, current)
    assert to_block == {(1, 10), (2, 10)}
    assert to_unblock == {(3, 99)}


def test_strip_removes_only_blocked_user_ids():
    result = strip_blocked_clients(base(), {2})
    emails = [c["email"] for c in result["inbounds"][0]["settings"]["clients"]]
    assert emails == ["1.alice", "10.carol"]


def test_strip_matches_full_uid_prefix_not_substring():
    result = strip_blocked_clients(base(), {1})
    emails = [c["email"] for c in result["inbounds"][0]["settings"]["clients"]]
    assert emails == ["2.bob", "10.carol"]


def test_strip_empty_set_returns_same_object():
    cfg = base()
    assert strip_blocked_clients(cfg, set()) is cfg


def test_strip_does_not_mutate_input():
    cfg = base()
    snapshot = copy.deepcopy(dict(cfg))
    strip_blocked_clients(cfg, {1, 2})
    assert dict(cfg) == snapshot


def test_aggregate_sums_only_current_month():
    rows = [
        {"user_id": 1, "monthly_used": 100, "monthly_period": "2026-06"},
        {"user_id": 1, "monthly_used": 50, "monthly_period": "2026-06"},
        {"user_id": 1, "monthly_used": 999, "monthly_period": "2026-05"},
    ]
    totals = aggregate_bs_usage(rows, "2026-06")
    assert totals[1] == 150


def test_over_limit_only_set_limits():
    assert over_limit(10, 0) is False
    assert over_limit(10, 10) is True
    assert over_limit(5, 10) is False


def test_pick_bs_bar_monthly():
    assert pick_bs_bar(8, 10) == (8, 10)
    assert pick_bs_bar(8, 0) is None


def test_monthly_pool_ceiling_is_stable_within_month():
    """3 ГБ/месяц + купленные 2 ГБ: потолок стоит на 5 ГБ, пока месяц не сменится."""
    gb = 1024**3
    monthly_limit = 3 * gb
    pool = 2 * gb

    assert monthly_effective_limit(monthly_limit, pool) == 5 * gb
    assert not over_limit_monthly_pool(2 * gb, monthly_limit, pool)
    assert not over_limit_monthly_pool(4 * gb, monthly_limit, pool)
    assert over_limit_monthly_pool(5 * gb, monthly_limit, pool)
    # потолок не зависит от израсходованного — он тот же при любом used
    assert monthly_effective_limit(monthly_limit, pool) == 5 * gb

    # смена месяца: расход 4 ГБ съедает 1 ГБ пула, остаток переносится
    pool = carry_over_pool(pool, 4 * gb, monthly_limit)
    assert pool == 1 * gb
    assert monthly_effective_limit(monthly_limit, pool) == 4 * gb


def test_over_limit_monthly_pool_zero_limit():
    assert over_limit_monthly_pool(100, 0, 0) is False


def test_bs_stub_remark_joins_nonempty_lines():
    assert bs_stub_remark(["лимит исчерпан", "ждите месяц"]) == "лимит исчерпан ждите месяц"


def test_bs_stub_remark_string_and_blanks():
    assert bs_stub_remark("один") == "один"
    assert bs_stub_remark(["", "  ", "x"]) == "x"


def test_bs_stub_remark_empty_inputs():
    assert bs_stub_remark([]) == ""
    assert bs_stub_remark(None) == ""


def test_carry_over_keeps_pool_when_base_not_exceeded():
    gb = 1024**3
    assert carry_over_pool(10 * gb, 2 * gb, 3 * gb) == 10 * gb


def test_carry_over_subtracts_only_overflow_above_base():
    gb = 1024**3
    assert carry_over_pool(10 * gb, 8 * gb, 3 * gb) == 5 * gb


def test_carry_over_drains_pool_when_ceiling_reached():
    gb = 1024**3
    assert carry_over_pool(10 * gb, 13 * gb, 3 * gb) == 0


def test_carry_over_never_goes_negative():
    gb = 1024**3
    assert carry_over_pool(10 * gb, 100 * gb, 3 * gb) == 0


def test_carry_over_without_limit_keeps_pool_intact():
    assert carry_over_pool(500, 999, 0) == 500


def test_carry_over_none_pool_is_zero():
    assert carry_over_pool(None, 999, 3) == 0


def _import_review_bs_nodes():
    """app.jobs.review_bs_nodes тянет app.db.models → app.models.user → app.subscription.share,
    а тот в песочнице conftest (app.subscription заглушен пустым пакетом без __init__)
    не находит свои же символы через `from . import *`. Тот же приём, что и в
    tests/test_record_bs_usage.py — подменяем только лист share на лёгкую заглушку, но
    только на время импорта: если заглушку поставили мы, сразу после импорта убираем её
    за собой, чтобы не протекала в sys.modules для других тестовых файлов."""
    import sys
    import types

    had_share_stub = "app.subscription.share" not in sys.modules
    if had_share_stub:
        share_stub = types.ModuleType("app.subscription.share")
        share_stub.generate_v2ray_links = lambda *args, **kwargs: []
        sys.modules["app.subscription.share"] = share_stub

    try:
        from app.jobs import review_bs_nodes
    finally:
        if had_share_stub:
            sys.modules.pop("app.subscription.share", None)

    return review_bs_nodes


def test_stale_sum_for_review_respects_pool_period():
    """Батч-логика review_bs_nodes: суммируем только периоды >= периода пула."""
    _stale_used_since = _import_review_bs_nodes()._stale_used_since

    rows = [("2000-01", 99), ("2000-02", 8), ("2000-03", 2)]
    assert _stale_used_since(rows, "2000-02") == 10
    assert _stale_used_since(rows, "2000-01") == 109
    assert _stale_used_since(rows, "2001-01") == 0
    assert _stale_used_since([], "2000-01") == 0


def test_review_effective_pool_matches_carry_over_cases():
    """Решение «блокировать или нет» считается батчем мимо канонического пути —
    поэтому те же кейсы, что у carry_over_pool, проверяем и здесь."""
    gb = 1024**3
    _effective_pool = _import_review_bs_nodes()._effective_pool
    now = "2000-03"
    rows = [("2000-01", 99 * gb), ("2000-02", 8 * gb)]

    # период пула = текущий месяц → пул как есть, несброшенные строки не вычитаем
    assert _effective_pool(10 * gb, now, now, rows, 3 * gb) == 10 * gb
    # период пула не заполнен (старые юзера до NPVPN-1768) → пул как есть
    assert _effective_pool(10 * gb, None, now, rows, 3 * gb) == 10 * gb
    # период отстал → вычитаем перерасход прошлого месяца сверх базы
    assert _effective_pool(10 * gb, "2000-02", now, rows, 3 * gb) == 5 * gb
    # строка старше периода пула уже учтена — второй раз не вычитается
    assert _effective_pool(10 * gb, "2000-02", now, rows, 3 * gb) == carry_over_pool(10 * gb, 8 * gb, 3 * gb)
    # расход не превысил базу → пул цел
    assert _effective_pool(10 * gb, "2000-02", now, [("2000-02", 2 * gb)], 3 * gb) == 10 * gb
    # потолок выбран полностью → пул обнуляется, но не уходит в минус
    assert _effective_pool(10 * gb, "2000-02", now, [("2000-02", 100 * gb)], 3 * gb) == 0
    # лимит бота не задан → пул не трогаем
    assert _effective_pool(10 * gb, "2000-02", now, [("2000-02", 100 * gb)], 0) == 10 * gb
