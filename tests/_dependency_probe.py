"""Изолированные проверки реального приложения без рабочих БД и внешних эффектов."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = json.loads((Path(__file__).parent / "fixtures/dependency_legacy.json").read_text())


def load_application():
    import requests

    original_get = requests.get

    def discovery_get(url, *args, **kwargs):
        # Только внешний discovery IP, не HTTP-клиенты проверяемого приложения.
        if url in {"http://api4.ipify.org/", "http://ipv4.icanhazip.com/", "https://ifconfig.io/ip"}:
            response = requests.Response()
            response.status_code = 200
            response._content = b"8.8.8.8"
            return response
        if url in {"http://api6.ipify.org/", "http://ipv6.icanhazip.com/"}:
            response = requests.Response()
            response.status_code = 200
            response._content = b"2001:4860:4860::8888"
            return response
        return original_get(url, *args, **kwargs)

    requests.get = discovery_get
    try:
        from app import app
    finally:
        requests.get = original_get

    from app.db import Base, SessionLocal, engine
    from app.db.models import JWT, Admin

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(JWT(secret_key=FIXTURES["secret"]))
        db.add(Admin(username="dependency_admin", hashed_password=FIXTURES["argon2"], is_sudo=True))
        db.commit()
    return app


def api_contract():
    app = load_application()
    from fastapi.testclient import TestClient

    from app import xray
    from app.utils import report

    # Изолированы только отправка уведомлений и изменение настоящих Xray-нод.
    for name in ("login", "user_created", "user_updated", "status_change"):
        setattr(report, name, lambda *_args, **_kwargs: None)
    for name in ("add_user", "update_user", "remove_user"):
        setattr(xray.operations, name, lambda *_args, **_kwargs: None)

    client = TestClient(app)
    denied = client.get("/api/user/compatibility_user")
    assert denied.status_code == 401, denied.text
    failed = client.post("/api/admin/token", data={"username": "dependency_admin", "password": "wrong"})
    assert failed.status_code == 401, failed.text
    login = client.post("/api/admin/token", data={"username": "dependency_admin", "password": FIXTURES["password"]})
    assert login.status_code == 200, login.text
    assert login.json()["token_type"] == "bearer"
    client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    payload = {"username": "compatibility_user", "proxies": {"vless": {}}, "expire": 2000000000, "data_limit": 1024}
    created = client.post("/api/user", json=payload)
    assert created.status_code == 200, created.text
    assert created.json()["username"] == "compatibility_user"
    assert created.json()["expire"] == 2000000000
    assert isinstance(created.json()["subscription_url"], str)
    updated = client.put("/api/user/compatibility_user", json={"expire": 2100000000})
    assert updated.status_code == 200, updated.text
    read = client.get("/api/user/compatibility_user")
    assert read.status_code == 200, read.text
    assert read.json()["expire"] == 2100000000
    invalid = client.post("/api/user", json={"username": "!", "proxies": {}})
    assert invalid.status_code == 422, invalid.text
    assert "username" in invalid.json()["detail"]
    client.close()


def password_contract():
    load_application()
    from app.models.admin import AdminCreate, AdminInDB

    for scheme in ("argon2", "bcrypt"):
        admin = AdminInDB(username="legacy_admin", is_sudo=True, hashed_password=FIXTURES[scheme])
        assert admin.verify_password(FIXTURES["password"])
        assert not admin.verify_password("wrong-password")
    new = AdminCreate(username="new_admin", is_sudo=True, password=FIXTURES["password"])
    assert AdminInDB(username="new_admin", is_sudo=True, hashed_password=new.hashed_password).verify_password(
        FIXTURES["password"]
    )
    supplied = AdminCreate(username="import_admin", is_sudo=True, password_hash=FIXTURES["argon2"])
    assert supplied.hashed_password == FIXTURES["argon2"]


def jwt_contract():
    load_application()
    import jwt

    from app.utils import jwt as tokens

    # Источник legacy-секретов из настроек изолирован, сами подписи настоящие.
    tokens.get_subscription_secret_keys = lambda: ["new-test-key-32-characters-long-value", FIXTURES["secret"]]
    assert tokens.get_subscription_payload(FIXTURES["compact"])["username"] == "compact_user"
    assert tokens.get_subscription_payload(FIXTURES["legacy"])["username"] == "legacy_user"
    assert tokens.get_subscription_payload(FIXTURES["compact"][:-10] + "AAAAAAAAAA") is None
    wrong = jwt.encode(
        {"sub": "legacy_user", "access": "subscription", "iat": 1700000000},
        "wrong-test-key-32-characters-long-value",
        algorithm="HS256",
    )
    assert tokens.get_subscription_payload(wrong) is None
    token = tokens.create_admin_token("dependency_admin", is_sudo=True)
    assert tokens.get_admin_payload(token)["is_sudo"] is True
    expired = jwt.encode(
        {"sub": "dependency_admin", "access": "sudo", "iat": 1700000000, "exp": 1700000010},
        FIXTURES["secret"],
        algorithm="HS256",
    )
    assert tokens.get_admin_payload(expired) is None


def db_contract():
    load_application()
    from sqlalchemy import Column, Integer, text

    from app.db import Base, SessionLocal, engine

    class Pending(Base):
        __tablename__ = "dependency_pending"
        id = Column(Integer, primary_key=True)

    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add(Pending(id=1))
        assert db.execute(text("SELECT count(*) FROM dependency_pending")).scalar() == 0
        db.commit()
        assert db.execute(text("SELECT count(*) FROM dependency_pending")).scalar() == 1
        db.add(Pending(id=2))
        db.rollback()
        assert db.execute(text("SELECT count(*) FROM dependency_pending")).scalar() == 1


def grpc_contract():
    load_application()
    import importlib
    from concurrent.futures import ThreadPoolExecutor
    from uuid import UUID

    import grpc

    from xray_api import XRay
    from xray_api.proto.app.proxyman.command import command_pb2 as proxy
    from xray_api.proto.app.proxyman.command import command_pb2_grpc as proxy_rpc
    from xray_api.proto.app.stats.command import command_pb2 as stats
    from xray_api.proto.app.stats.command import command_pb2_grpc as stats_rpc
    from xray_api.proto.proxy.vless import account_pb2
    from xray_api.types.account import VLESSAccount

    for path in (ROOT / "xray_api/proto").rglob("*_pb2*.py"):
        importlib.import_module(".".join(path.relative_to(ROOT).with_suffix("").parts))

    class Handler(proxy_rpc.HandlerServiceServicer):
        def AlterInbound(self, request, _context):
            assert request.tag == "test-vless"
            operation = proxy.AddUserOperation.FromString(request.operation.value)
            assert operation.user.email == "compat@example.test"
            account = account_pb2.Account.FromString(operation.user.account.value)
            assert account.id == "cae50f61-2514-4a88-812f-215566e4c117"
            return proxy.AlterInboundResponse()

    class Stats(stats_rpc.StatsServiceServicer):
        def QueryStats(self, request, _context):
            assert request.pattern == "user>>>"
            return stats.QueryStatsResponse(
                stat=[stats.Stat(name="user>>>compat@example.test>>>traffic>>>uplink", value=42)]
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        server = grpc.server(executor)
        proxy_rpc.add_HandlerServiceServicer_to_server(Handler(), server)
        stats_rpc.add_StatsServiceServicer_to_server(Stats(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        client = XRay("127.0.0.1", port)
        try:
            user = VLESSAccount(email="compat@example.test", id=UUID("cae50f61-2514-4a88-812f-215566e4c117"))
            assert client.add_inbound_user("test-vless", user, timeout=5)
            result = list(client.get_users_stats(timeout=5))
            assert [(r.name, r.value, r.link) for r in result] == [("compat@example.test", 42, "uplink")]
        finally:
            client._channel.close()
            server.stop(0).wait(timeout=5)


def _check_rest_transport(node, pem, received, release_response):
    import pytest

    from app.xray.node import NodeAPIError

    node.session.trust_env = False
    with pytest.raises(NodeAPIError, match="CERTIFICATE_VERIFY_FAILED"):
        node.make_request("/restart", timeout=5, config="untrusted")
    assert node._session_id == "compat-control-session"
    node._node_cert = pem["cert"]
    node._refresh_http_transport()
    node.session.trust_env = False
    result = node.make_request("/restart", timeout=90, config="x" * 1048576)
    assert result == {"accepted": 1048576}
    assert received[0]["session_id"] == "compat-control-session"
    assert len(received) == 1
    with pytest.raises(NodeAPIError, match="(?i)timed out") as error:
        node.make_request("/timeout", timeout=1, config="timeout-probe")
    assert error.value.status_code == 0
    assert node._session_id == "compat-control-session"
    release_response.set()
    node.session.trust_env = False
    assert node.make_request("/restart", timeout=5, config="recovered") == {"accepted": 9}
    assert [r["session_id"] for r in received] == ["compat-control-session"] * 3


def rest_contract():
    load_application()
    import ssl
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from app.utils.crypto import generate_certificate
    from app.xray.node import ReSTXRayNode

    received = []
    release_response = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(payload)
            if self.path == "/timeout":
                release_response.wait(timeout=5)
                return
            body = json.dumps({"accepted": len(payload["config"])}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    pem = generate_certificate()
    directory = Path(
        tempfile.mkdtemp(dir=Path(os.environ["SQLALCHEMY_DATABASE_URL"].removeprefix("sqlite:///")).parent)
    )
    certfile, keyfile = directory / "cert.pem", directory / "key.pem"
    certfile.write_text(pem["cert"])
    keyfile.write_text(pem["key"])
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile, keyfile)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    node = ReSTXRayNode("127.0.0.1", server.server_port, 1, pem["key"], pem["cert"])
    node._session_id = "compat-control-session"
    try:
        _check_rest_transport(node, pem, received, release_response)
    finally:
        release_response.set()
        node.release_local()
        node._keyfile.close()
        node._certfile.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def cli_contract():
    load_application()
    import runpy

    from typer.testing import CliRunner

    application = runpy.run_path(str(ROOT / "marzban-cli.py"))["app"]
    runner = CliRunner()
    for args in (
        ["--help"],
        ["admin", "--help"],
        ["user", "--help"],
        ["subscription", "--help"],
        ["user", "list", "--help"],
    ):
        result = runner.invoke(application, args)
        assert result.exit_code == 0, (args, result.output, result.exception)
    shown = runner.invoke(application, ["completion", "show", "--shell", "bash"])
    assert shown.exit_code == 0, (shown.output, shown.exception)
    assert "complete" in shown.output
    listed = runner.invoke(application, ["user", "list", "--username", "alice", "--username", "bob", "--limit", "2"])
    assert listed.exit_code == 0, (listed.output, listed.exception)
    assert "Username" in listed.output
    from app.db import SessionLocal
    from app.db.models import Admin

    with SessionLocal() as db:
        db.add(Admin(username="cli_delete_me", hashed_password=FIXTURES["argon2"], is_sudo=False))
        db.commit()
    deleted = runner.invoke(application, ["admin", "delete", "--username", "cli_delete_me", "--yes"])
    assert deleted.exit_code == 0, (deleted.output, deleted.exception)
    with SessionLocal() as db:
        assert db.query(Admin).filter_by(username="cli_delete_me").first() is None

    import contextlib
    import io

    output = io.StringIO()
    previous_argv = sys.argv
    try:
        sys.argv = [str(ROOT / "marzban-cli.py"), "--help"]
        with contextlib.redirect_stdout(output):
            try:
                runpy.run_path(str(ROOT / "marzban-cli.py"), run_name="__main__")
            except SystemExit as exc:
                assert exc.code == 0
        assert "Usage" in output.getvalue()
    finally:
        sys.argv = previous_argv


def _exercise_scheduler_error(scheduler, error_logged):
    scheduler.remove_all_jobs()

    def fail():
        raise RuntimeError

    scheduler.add_job(fail, "date", id="dependency-probe")
    scheduler.resume()
    assert error_logged.wait(timeout=5), "Scheduler failure listener did not log the job error"
    scheduler.pause()


def _isolate_dashboard(dashboard):
    dashboard_dir = Path(os.environ["SQLALCHEMY_DATABASE_URL"].removeprefix("sqlite:///")).parent / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "statics").mkdir()
    dashboard.DEBUG = False
    dashboard.build_dir = dashboard_dir
    dashboard.statics_dir = dashboard_dir / "statics"


def lifecycle_contract():
    os.environ["TELEGRAM_API_TOKEN"] = "123456:synthetic-token-not-used-for-network"
    os.environ["TELEGRAM_ADMIN_ID"] = "42"
    load_application()
    import logging
    import threading

    from fastapi import APIRouter
    from fastapi.testclient import TestClient

    import app
    import app.telegram as telegram

    events = []
    error_logged = threading.Event()

    class Capture(logging.Handler):
        def emit(self, record):
            if "dependency-probe" in record.getMessage() and record.levelno >= logging.ERROR:
                error_logged.set()

    class PollingThread:
        def __init__(self, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    _isolate_dashboard(app.dashboard)
    app.scheduler.remove_all_jobs()
    app.xray.core.start = lambda _config: events.append("xray.start")
    app.xray.core.stop = lambda: events.append("xray.stop")
    telegram.Thread = PollingThread
    telegram.get_bot().infinity_polling = lambda: events.append("telegram.poll")
    app._setup_file_logging = lambda: events.append("logging")
    original_start, original_stop = app.scheduler.start, app.scheduler.shutdown

    def start_scheduler():
        events.append("scheduler.start")
        original_start(paused=True)

    def stop_scheduler():
        events.append("scheduler.stop")
        original_stop()

    app.scheduler.start, app.scheduler.shutdown = start_scheduler, stop_scheduler
    capture = Capture()
    app.logger.addHandler(capture)
    try:
        with TestClient(app.app):
            assert events == ["telegram.poll", "xray.start", "logging", "scheduler.start"], events
            assert app.scheduler.running
            assert "is_admin" in telegram.get_bot().custom_filters
            _exercise_scheduler_error(app.scheduler, error_logged)
        assert events[-2:] == ["xray.stop", "scheduler.stop"]
        assert not app.scheduler.running
    finally:
        app.logger.removeHandler(capture)

    nested = APIRouter()
    nested.add_api_route("/blocked", lambda: None, include_in_schema=False)
    app.app.include_router(nested, prefix="/dependency-nested")
    app.XRAY_SUBSCRIPTION_PATH = "dependency-nested/blocked"
    import pytest

    with pytest.raises(ValueError, match="reserved"):
        app.on_startup()


def telegram_filters_contract():
    load_application()
    import pytest

    import app.telegram as telegram

    with pytest.raises(RuntimeError):
        telegram.get_bot()
    from telebot import types

    from app.telegram.utils.custom_filters import cb_query_equals, cb_query_startswith

    base = {
        "id": "callback",
        "from": {"id": 42, "is_bot": False, "first_name": "Admin"},
        "chat_instance": "test",
        "data": "system",
    }
    message = {"message_id": 1, "date": 1700000000, "chat": {"id": 42, "type": "private"}, "text": "Panel"}
    valid = types.CallbackQuery.de_json({**base, "message": message})
    assert cb_query_equals("system")(valid)
    assert cb_query_startswith("sys")(valid)
    for payload in (base, {**base, "data": None, "message": message}, {**base, "message": {**message, "date": 0}}):
        query = types.CallbackQuery.de_json(payload)
        assert not cb_query_equals("system")(query)
        assert not cb_query_startswith("sys")(query)


def telegram_registration_contract():
    os.environ["TELEGRAM_API_TOKEN"] = "123456:synthetic-token-not-used-for-network"
    os.environ["TELEGRAM_ADMIN_ID"] = "42"
    load_application()
    import importlib.util

    import app.telegram as telegram

    assert telegram.get_bot() is telegram.bot
    modules = {}
    for name in ("admin", "user"):
        spec = importlib.util.spec_from_file_location(
            "dependency_" + name, ROOT / "app/telegram/handlers" / (name + ".py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules[name] = module
    from app.telegram.utils.custom_filters import setup

    setup()
    assert telegram.bot.message_handlers
    assert telegram.bot.callback_query_handlers
    assert "is_admin" in telegram.bot.custom_filters
    from telebot import types

    edited = []
    response = types.Message.de_json(
        {"message_id": 1, "date": 1700000000, "chat": {"id": 42, "type": "private"}, "text": "Panel"}
    )
    telegram.bot.edit_message_text = lambda *args, **_kwargs: edited.append(args) or response
    telegram.bot.threaded = False
    for sender in (43, 42):
        query = types.CallbackQuery.de_json(
            {
                "id": "callback",
                "from": {"id": sender, "is_bot": False, "first_name": "Admin"},
                "chat_instance": "test",
                "data": "restart",
                "message": {
                    "message_id": 1,
                    "date": 1700000000,
                    "chat": {"id": 42, "type": "private"},
                    "text": "Panel",
                },
            }
        )
        telegram.bot.process_new_callback_query([query])
    assert len(edited) == 1

    incoming = types.Message.de_json({"message_id": 1, "date": 1700000000, "chat": {"id": 42, "type": "private"}})
    sent = []

    def send_message(chat_id, text, *_args, **_kwargs):
        sent.append(text)
        return types.Message.de_json(
            {"message_id": 2, "date": 1700000000, "chat": {"id": chat_id, "type": "private"}, "text": text}
        )

    telegram.bot.send_message = send_message
    for handler in (modules["admin"].edit_user_data_limit_step, modules["admin"].edit_user_expire_on_hold_timeout_step):
        handler(incoming, username="compatibility_user")
        retry = telegram.bot.next_step_backend.get_handlers(42)
        assert len(retry) == 1
        assert retry[0].callback is handler
    assert len(sent) == 2


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="panel-dependency-probe-") as directory:
        os.environ["SQLALCHEMY_DATABASE_URL"] = f"sqlite:///{directory}/test.sqlite3"
        os.environ["DEBUG"] = "false"
        os.environ["SUDO_USERNAME"] = ""
        os.environ["SUDO_PASSWORD"] = ""
        os.environ["TELEGRAM_API_TOKEN"] = ""
        os.environ["XRAY_JSON"] = str(ROOT / "xray_config.json")
        os.environ["WEBHOOK_ADDRESS"] = ""
        os.chdir(ROOT)
        {
            "api": api_contract,
            "password": password_contract,
            "jwt": jwt_contract,
            "db": db_contract,
            "grpc": grpc_contract,
            "rest": rest_contract,
            "cli": cli_contract,
            "lifecycle": lifecycle_contract,
            "telegram_filters": telegram_filters_contract,
            "telegram_registration": telegram_registration_contract,
        }[sys.argv[1]]()
