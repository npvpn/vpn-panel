from app.subscription.address_context import AddressContext, HostSubsetSettings, weighted_candidates


def ctx(**kwargs):
    base = dict(user_id=42, day_index=0, enabled=True)
    base.update(kwargs)
    return AddressContext(**base)


def host(size=2, rotation_days=1, enabled=True):
    return HostSubsetSettings(enabled=enabled, size=size, rotation_days=rotation_days)


ADDRESSES = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]
NODE_IDS = [11, 22, 33, 44]


def pick(context, *, settings=None, addresses=None, node_ids=None, addresses_from_nodes=True, host_id=None):
    return context.pick(
        ADDRESSES if addresses is None else addresses,
        NODE_IDS if node_ids is None else node_ids,
        addresses_from_nodes=addresses_from_nodes,
        host_id=host_id,
        settings=host() if settings is None else settings,
    )


def test_disabled_context_returns_everything():
    assert pick(AddressContext.disabled()) == ADDRESSES


def test_host_without_subset_returns_everything():
    """Настройка живёт на хосте: выключена у хоста — сужения нет (NPVPN-2072)."""
    assert pick(ctx(), settings=host(enabled=False)) == ADDRESSES
    assert pick(ctx(), settings=host(size=0)) == ADDRESSES


def test_narrows_to_size():
    picked = pick(ctx())
    assert len(picked) == 2
    assert set(picked) <= set(ADDRESSES)


def test_preserves_original_order():
    picked = pick(ctx(), settings=host(size=3))
    assert picked == [a for a in ADDRESSES if a in picked]


def test_not_narrowed_when_addresses_fit():
    assert pick(ctx(), settings=host(size=4)) == ADDRESSES
    assert pick(ctx(), settings=host(size=9)) == ADDRESSES


def test_two_hosts_can_hand_out_different_counts():
    """Ровно то, ради чего настройка уехала на хост: 2 адреса на одном, 3 на другом."""
    context = ctx()
    assert len(pick(context, settings=host(size=2))) == 2
    assert len(pick(context, settings=host(size=3))) == 3


def test_same_nodes_across_hosts_of_one_location():
    """vless- и trojan-хосты на одном парке нод дают юзеру одни и те же ноды."""
    vless = pick(ctx())
    trojan_addresses = ["a.example", "b.example", "c.example", "d.example"]
    trojan = pick(ctx(), addresses=trojan_addresses)
    vless_nodes = [n for a, n in zip(ADDRESSES, NODE_IDS) if a in vless]
    trojan_nodes = [n for a, n in zip(trojan_addresses, NODE_IDS) if a in trojan]
    assert vless_nodes == trojan_nodes


def test_weights_push_user_to_node_with_more_headroom():
    heavy = {11: 0.0, 22: 0.0, 33: 10**12, 44: 10**12}
    assert set(pick(ctx(weights_by_day={0: heavy}))) == {"3.3.3.3", "4.4.4.4"}


def test_weights_are_taken_for_the_epoch_of_this_host():
    """Период ротации пер-хостовый, поэтому снимок берётся на начало ЕГО эпохи.

    Для user_id=42 и day_index=7 эпоха при периоде 1 начинается в день 7, при периоде 6 —
    в день 3 (сдвиг _smear размазывает ротацию по юзерам). Разные дни снимка обязаны дать
    разные наборы — иначе пер-хостовый период ротации был бы фикцией.
    """
    from app.xray.address_policy import epoch_start_day

    fast_day = epoch_start_day(42, 7, 1)
    slow_day = epoch_start_day(42, 7, 6)
    assert fast_day != slow_day, "sanity: периоды обязаны давать разные сутки снимка"

    context = ctx(
        day_index=7,
        weights_by_day={
            fast_day: {11: 10**12, 22: 10**12, 33: 0.0, 44: 0.0},
            slow_day: {11: 0.0, 22: 0.0, 33: 10**12, 44: 10**12},
        },
    )
    assert set(pick(context, settings=host(rotation_days=1))) == {"1.1.1.1", "2.2.2.2"}
    assert set(pick(context, settings=host(rotation_days=6))) == {"3.3.3.3", "4.4.4.4"}


def test_never_empty_when_every_node_exhausted_by_weight():
    zero = dict.fromkeys(NODE_IDS, 0.0)
    assert len(pick(ctx(weights_by_day={0: zero}))) == 2


def test_exhausted_node_is_dropped_before_weighting():
    """Порог — стоп-кран, а не предпочтение: перешагнувшая нода не выдаётся вовсе."""
    context = ctx(exhausted=frozenset({11, 22}))
    for user_id in range(50):
        picked = ctx(user_id=user_id, exhausted=frozenset({11, 22})).pick(
            ADDRESSES, NODE_IDS, addresses_from_nodes=True, settings=host()
        )
        assert set(picked) == {"3.3.3.3", "4.4.4.4"}
    assert set(pick(context)) == {"3.3.3.3", "4.4.4.4"}


def test_exhausted_beats_weight():
    """Даже с огромным остатком по снимку исчерпанная нода выбывает: свежие данные важнее."""
    stale = {11: 10**12, 22: 10**12, 33: 0.0, 44: 0.0}
    picked = pick(ctx(weights_by_day={0: stale}, exhausted=frozenset({11, 22})))
    assert set(picked) == {"3.3.3.3", "4.4.4.4"}


def test_fewer_alive_than_size_yields_what_is_left():
    """Живых меньше размера подмножества — отдаём остаток, а не добираем исчерпанными."""
    picked = pick(ctx(exhausted=frozenset({11, 22, 33})), settings=host(size=2))
    assert picked == ["4.4.4.4"]


def test_whole_host_exhausted_falls_back_to_full_set():
    """Инвариант «подписка не остаётся без адресов» жёстче экономии трафика."""
    picked = pick(ctx(exhausted=frozenset(NODE_IDS)), settings=host(size=2))
    assert len(picked) == 2
    assert set(picked) <= set(ADDRESSES)


def test_exhausted_does_not_touch_static_address_host():
    """У легаси-хоста соответствия «адрес ↔ нода» нет — судить об исчерпании нечем."""
    picked = pick(ctx(exhausted=frozenset(NODE_IDS)), addresses_from_nodes=False)
    assert len(picked) == 2


def test_legacy_static_addresses_without_node_match():
    """host.address задан строкой: node_ids — все привязанные ноды без порядкового
    соответствия адресам. addresses_from_nodes=False режет по самим адресам."""
    picked = pick(ctx(), node_ids=[11, 22], addresses_from_nodes=False)
    assert len(picked) == 2
    assert set(picked) <= set(ADDRESSES)


def test_static_address_ignores_weights_even_when_lengths_match():
    """NPVPN-2072 (регресс главной находки): раньше ветка взвешивания выбиралась по
    len(node_ids) == len(addresses). Хост со статическим host.address и случайно
    совпавшим числом привязанных нод молча получал веса от чужих нод. Теперь
    признак приходит явно (addresses_from_nodes=False), и веса не участвуют вовсе.
    """
    heavy = {11: 0.0, 22: 0.0, 33: 10**12, 44: 10**12}
    inverted = {11: 10**12, 22: 10**12, 33: 0.0, 44: 0.0}

    weighted_heavy = pick(ctx(weights_by_day={0: heavy}))
    weighted_inverted = pick(ctx(weights_by_day={0: inverted}))
    assert set(weighted_heavy) != set(weighted_inverted), "sanity: weighting must react to weights"

    static_heavy = pick(ctx(weights_by_day={0: heavy}), addresses_from_nodes=False)
    static_inverted = pick(ctx(weights_by_day={0: inverted}), addresses_from_nodes=False)
    assert static_heavy == static_inverted, "статический адрес не должен реагировать на weights"


def test_legacy_selection_is_deterministic():
    first = pick(ctx(), node_ids=[], addresses_from_nodes=False)
    second = pick(ctx(), node_ids=[], addresses_from_nodes=False)
    assert first == second


def test_size_one_yields_single_address():
    """N = 1 разрешён; следствие — add_balanced в share.py не сработает."""
    assert len(pick(ctx(), settings=host(size=1))) == 1


def test_unknown_node_gets_median_not_zero():
    weights = weighted_candidates({11: 100.0, 22: 300.0}, [11, 22, 33])
    assert weights[33] == 200.0


def test_all_unknown_degrades_to_unweighted():
    assert weighted_candidates({}, [11, 22]) == {11: 0.0, 22: 0.0}


def test_node_without_limit_competes_on_equal_terms():
    """У ноды 44 веса нет; медиана не даёт ей проиграть всем подряд."""
    weights = {11: 10**12, 22: 10**12, 33: 10**12}
    seen = set()
    for user_id in range(200):
        seen.update(pick(ctx(user_id=user_id, weights_by_day={0: weights})))
    assert "4.4.4.4" in seen


def test_pin_replaces_computed_subset():
    """Закрепление заменяет автовыбор целиком — что задано, то и выдаётся."""
    picked = pick(ctx(pins={7: [33]}), host_id=7)
    assert picked == ["3.3.3.3"]


def test_pin_survives_exhaustion():
    """Пин сильнее порога: саппорт закрепил ноду явно, со сроком и автором."""
    picked = pick(ctx(pins={7: [33]}, exhausted=frozenset({33})), host_id=7)
    assert picked == ["3.3.3.3"]


def test_pin_applies_only_to_its_host():
    assert len(pick(ctx(pins={7: [33]}), host_id=99)) == 2


def test_pin_to_missing_node_falls_back_to_autochoice():
    """Закреплённой ноды больше нет у хоста — юзер не остаётся без адресов."""
    assert len(pick(ctx(pins={7: [777]}), host_id=7)) == 2


def test_pin_ignored_for_static_address_host():
    """У легаси-хоста соответствия «адрес ↔ нода» нет, закреплять нечего."""
    assert len(pick(ctx(pins={7: [33]}), addresses_from_nodes=False, host_id=7)) == 2
