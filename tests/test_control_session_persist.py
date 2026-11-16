"""Control sessions are stored when REST nodes connect."""

import sys
import types
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

for _name, _module in list(sys.modules.items()):
    if _name.startswith("app.") and not hasattr(_module, "__file__") and not hasattr(_module, "__path__"):
        del sys.modules[_name]

_share_stub = types.ModuleType("app.subscription.share")
_share_stub.generate_v2ray_links = lambda *args, **kwargs: []
sys.modules.setdefault("app.subscription.share", _share_stub)

from app.db import crud  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.models import Node  # noqa: E402
from app.xray import operations  # noqa: E402

if sys.modules.get("app.subscription.share") is _share_stub:
    del sys.modules["app.subscription.share"]


def test_add_node_listener_persists_session_id():
    dbnode = MagicMock()
    dbnode.id = 4
    dbnode.address = "10.0.0.8"
    dbnode.port = 62050
    dbnode.api_port = 62051
    dbnode.protocol = "rest"
    dbnode.usage_coefficient = 1.0
    created = MagicMock()

    with (
        patch.object(operations, "remove_node"),
        patch.object(operations, "get_tls", return_value={"key": "k", "certificate": "c"}),
        patch.object(operations, "XRayNode", return_value=created),
        patch.object(operations, "xray") as xray_mod,
        patch.object(operations, "_persist_control_session") as persist,
    ):
        xray_mod.nodes = {}
        operations.add_node(dbnode)
        created.set_control_session_listener.assert_called_once()
        listener = created.set_control_session_listener.call_args.args[0]
        listener("33333333-3333-3333-3333-333333333333")

    persist.assert_called_once_with(4, "33333333-3333-3333-3333-333333333333")


def test_control_session_is_committed_and_can_be_cleared(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'sessions.sqlite3'}")
    Base.metadata.create_all(engine, tables=[Node.__table__])
    try:
        with Session(engine) as db:
            db.add(Node(id=4, name="test-node", address="10.0.0.8", port=62050, api_port=62051))
            db.commit()
            crud.set_node_control_session(db, 4, "33333333-3333-3333-3333-333333333333")

        with Session(engine) as db:
            assert db.get(Node, 4).control_session_id == "33333333-3333-3333-3333-333333333333"
            crud.set_node_control_session(db, 4, None)

        with Session(engine) as db:
            assert db.get(Node, 4).control_session_id is None
    finally:
        engine.dispose()
