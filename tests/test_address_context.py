from app.subscription.address_context import AddressContext, weighted_candidates


def ctx(**kwargs):
    base = dict(user_id=42, size=2, epoch=0, weights={}, enabled=True)
    base.update(kwargs)
    return AddressContext(**base)


ADDRESSES = ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]
NODE_IDS = [11, 22, 33, 44]


def test_disabled_context_returns_everything():
    assert AddressContext.disabled().pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True) == ADDRESSES


def test_flag_off_returns_everything():
    assert ctx(enabled=False).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True) == ADDRESSES


def test_narrows_to_size():
    picked = ctx().pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)
    assert len(picked) == 2
    assert set(picked) <= set(ADDRESSES)


def test_preserves_original_order():
    picked = ctx(size=3).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)
    assert picked == [a for a in ADDRESSES if a in picked]


def test_not_narrowed_when_addresses_fit():
    assert ctx(size=4).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True) == ADDRESSES
    assert ctx(size=9).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True) == ADDRESSES


def test_same_nodes_across_hosts_of_one_location():
    """vless- и trojan-хосты на одном парке нод дают юзеру одни и те же ноды."""
    vless = ctx().pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)
    trojan_addresses = ["a.example", "b.example", "c.example", "d.example"]
    trojan = ctx().pick(trojan_addresses, NODE_IDS, addresses_from_nodes=True)
    vless_nodes = [n for a, n in zip(ADDRESSES, NODE_IDS) if a in vless]
    trojan_nodes = [n for a, n in zip(trojan_addresses, NODE_IDS) if a in trojan]
    assert vless_nodes == trojan_nodes


def test_weights_push_user_to_node_with_more_headroom():
    heavy = {11: 0.0, 22: 0.0, 33: 10**12, 44: 10**12}
    assert set(ctx(weights=heavy).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)) == {"3.3.3.3", "4.4.4.4"}


def test_never_empty_when_every_node_exhausted():
    zero = dict.fromkeys(NODE_IDS, 0.0)
    assert len(ctx(weights=zero).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)) == 2


def test_legacy_static_addresses_without_node_match():
    """host.address задан строкой: node_ids — все привязанные ноды без порядкового
    соответствия адресам. addresses_from_nodes=False режет по самим адресам."""
    picked = ctx().pick(ADDRESSES, [11, 22], addresses_from_nodes=False)
    assert len(picked) == 2
    assert set(picked) <= set(ADDRESSES)


def test_static_address_ignores_weights_even_when_lengths_match():
    """NPVPN-2072 (регресс главной находки): раньше ветка взвешивания выбиралась по
    len(node_ids) == len(addresses). Хост со статическим host.address и случайно
    совпавшим числом привязанных нод молча получал веса от чужих нод. Теперь
    признак приходит явно (addresses_from_nodes=False), и веса не участвуют вовсе:
    выбор по самим адресам с "нулевыми" кандидатами не зависит от содержимого weights,
    хотя node_ids и addresses по длине совпадают 1:1.
    """
    heavy = {11: 0.0, 22: 0.0, 33: 10**12, 44: 10**12}
    inverted = {11: 10**12, 22: 10**12, 33: 0.0, 44: 0.0}

    picked_weighted_heavy = ctx(weights=heavy).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)
    picked_weighted_inverted = ctx(weights=inverted).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)
    assert set(picked_weighted_heavy) != set(picked_weighted_inverted), "sanity: weighting must react to weights"

    picked_static_heavy = ctx(weights=heavy).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=False)
    picked_static_inverted = ctx(weights=inverted).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=False)
    assert picked_static_heavy == picked_static_inverted, "статический адрес не должен реагировать на weights"


def test_legacy_selection_is_deterministic():
    first = ctx().pick(ADDRESSES, [], addresses_from_nodes=False)
    second = ctx().pick(ADDRESSES, [], addresses_from_nodes=False)
    assert first == second


def test_size_one_yields_single_address():
    """N = 1 разрешён; следствие — add_balanced в share.py не сработает."""
    assert len(ctx(size=1).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True)) == 1


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
        seen.update(ctx(user_id=user_id, weights=weights).pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True))
    assert "4.4.4.4" in seen


def test_pin_replaces_computed_subset():
    """Закрепление заменяет автовыбор целиком — что задано, то и выдаётся."""
    ctx = AddressContext(user_id=42, size=2, epoch=0, weights={}, enabled=True, pins={7: [33]})
    picked = ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True, host_id=7)
    assert picked == ["3.3.3.3"]


def test_pin_applies_only_to_its_host():
    ctx = AddressContext(user_id=42, size=2, epoch=0, weights={}, enabled=True, pins={7: [33]})
    assert len(ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True, host_id=99)) == 2


def test_pin_to_missing_node_falls_back_to_autochoice():
    """Закреплённой ноды больше нет у хоста — юзер не остаётся без адресов."""
    ctx = AddressContext(user_id=42, size=2, epoch=0, weights={}, enabled=True, pins={7: [777]})
    assert len(ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=True, host_id=7)) == 2


def test_pin_ignored_for_static_address_host():
    """У легаси-хоста соответствия «адрес ↔ нода» нет, закреплять нечего."""
    ctx = AddressContext(user_id=42, size=2, epoch=0, weights={}, enabled=True, pins={7: [33]})
    picked = ctx.pick(ADDRESSES, NODE_IDS, addresses_from_nodes=False, host_id=7)
    assert len(picked) == 2


def test_managed_payload_carries_subset_settings_through():
    """Синк админка бота -> панель: ключ не должен молча отбрасываться allowlist'ом."""
    from app.models.managed import ManagedBotSettingsPayload

    payload = ManagedBotSettingsPayload.model_validate(
        {
            "username": "testbot",
            "bot_url": "https://t.me/testbot",
            "web_url": "",
            "sub_support_url": "",
            "sub_subscription_domain": "",
            "sub_address_subset_enabled": True,
            "sub_address_subset_size": 3,
            "sub_address_rotation_days": 5,
        }
    )
    dumped = payload.model_dump()
    assert dumped["sub_address_subset_enabled"] is True
    assert dumped["sub_address_subset_size"] == 3
    assert dumped["sub_address_rotation_days"] == 5
