from app.subscription.bs_context import ZERO_STUB, BsContext, StubEndpoint


def host(*node_ids):
    return {"address": ["example.com"], "node_ids": list(node_ids)}


def ctx(blocked=(), stub_text="лимит"):
    return BsContext(blocked_node_ids=frozenset(blocked), stub_text=stub_text)


def test_is_blocked_by_node_link():
    assert ctx(blocked=[7]).is_blocked(host(7)) is True
    assert ctx(blocked=[7]).is_blocked(host(3)) is False
    assert ctx(blocked=[7]).is_blocked(host(3, 7)) is True


def test_empty_context_matches_nothing():
    empty = BsContext.empty()
    assert empty.is_blocked(host(7)) is False
    assert empty.has_blocks is False
    assert empty.stub_text == ""


def test_has_blocks_reflects_blocked_nodes():
    assert ctx(blocked=[7]).has_blocks is True
    assert ctx(blocked=[]).has_blocks is False


def test_zero_stub_endpoint():
    assert ZERO_STUB == StubEndpoint(address="0.0.0.0", port=0)
