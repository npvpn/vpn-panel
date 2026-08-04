import re
import socket
import ssl
import tempfile
import threading
import time
from collections import deque
from contextlib import contextmanager

import grpc
import requests
import rpyc
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.poolmanager import PoolManager
from websocket import WebSocketConnectionClosedException, WebSocketTimeoutException, create_connection

from app.models.node import NodeProtocol
from app.xray.config import XRayConfig
from app.xray.node_config import inline_local_certificates
from config import (
    XRAY_NODE_CERT_FETCH_TIMEOUT,
    XRAY_NODE_GRPC_READY_RETRIES,
    XRAY_NODE_GRPC_READY_RETRY_DELAY,
    XRAY_NODE_GRPC_READY_TIMEOUT,
    XRAY_NODE_REST_CONNECT_TIMEOUT,
    XRAY_NODE_REST_DISCONNECT_TIMEOUT,
    XRAY_NODE_REST_INFO_TIMEOUT,
    XRAY_NODE_REST_PING_TIMEOUT,
    XRAY_NODE_REST_RESTART_TIMEOUT,
    XRAY_NODE_REST_START_TIMEOUT,
    XRAY_NODE_REST_STOP_TIMEOUT,
)
from xray_api import XRay as XRayAPI


def string_to_temp_file(content: str):
    file = tempfile.NamedTemporaryFile(mode="w+t")
    file.write(content)
    file.flush()
    return file


class SANIgnoringAdaptor(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections, maxsize=maxsize, block=block, assert_hostname=False)


class NodeAPIError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail


def _safe_close_grpc_channel(channel) -> None:
    if channel is None:
        return
    try:
        channel.close()
    except Exception:
        pass


def wait_for_grpc_ready(
    address: str,
    port: int,
    ssl_cert: bytes,
    ssl_target_name: str = "Gozargah",
) -> XRayAPI:
    retries = max(1, XRAY_NODE_GRPC_READY_RETRIES)
    timeout = max(1, XRAY_NODE_GRPC_READY_TIMEOUT)
    retry_delay = max(0, XRAY_NODE_GRPC_READY_RETRY_DELAY)
    last_exc = None

    for attempt in range(1, retries + 1):
        api = XRayAPI(
            address=address,
            port=port,
            ssl_cert=ssl_cert,
            ssl_target_name=ssl_target_name,
        )
        try:
            grpc.channel_ready_future(api._channel).result(timeout=timeout)
            return api
        except (grpc.FutureTimeoutError, grpc.FutureCancelledError, ValueError) as exc:
            last_exc = exc
            # Stop orphaned connectivity polling threads before the next attempt.
            _safe_close_grpc_channel(api._channel)
            if attempt < retries and retry_delay:
                time.sleep(retry_delay)

    raise ConnectionError(
        f"Failed to connect to node's API after {retries} attempts "
        f"(timeout={timeout}s, delay={retry_delay}s): {last_exc}"
    )


def fetch_server_certificate(address: str, port: int, timeout: int) -> str:
    try:
        context = ssl._create_unverified_context()
        with socket.create_connection((address, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            with context.wrap_socket(sock, server_hostname=address) as tls_sock:
                cert = tls_sock.getpeercert(binary_form=True)
        return ssl.DER_cert_to_PEM_cert(cert)
    except TimeoutError as exc:
        raise ConnectionError(f"Timed out while fetching node certificate from {address}:{port}") from exc
    except Exception as exc:
        raise ConnectionError(f"Failed to fetch node certificate from {address}:{port}: {exc}") from exc


class ReSTXRayNode:
    def __init__(
        self, address: str, port: int, api_port: int, ssl_key: str, ssl_cert: str, usage_coefficient: float = 1
    ):

        self.address = address
        self.port = port
        self.api_port = api_port
        self.ssl_key = ssl_key
        self.ssl_cert = ssl_cert
        self.usage_coefficient = usage_coefficient

        self._keyfile = string_to_temp_file(ssl_key)
        self._certfile = string_to_temp_file(ssl_cert)

        self.session = requests.Session()
        self.session.mount("https://", SANIgnoringAdaptor())
        self.session.cert = (self._certfile.name, self._keyfile.name)

        self._session_id = None
        self._rest_api_url = f"https://{self.address.strip('/')}:{self.port}"

        self._ssl_context = ssl.create_default_context()
        self._ssl_context.check_hostname = False
        self._ssl_context.verify_mode = ssl.CERT_NONE
        self._ssl_context.load_cert_chain(certfile=self.session.cert[0], keyfile=self.session.cert[1])
        self._logs_ws_url = f"wss://{self.address.strip('/')}:{self.port}/logs"
        self._logs_queues = []
        self._logs_bg_thread = threading.Thread(target=self._bg_fetch_logs, daemon=True)

        self._api = None
        self._started = False
        self._grpc_lock = threading.Lock()

        # Реальный набор тегов инбаундов ноды; заполняется после успешного
        # start/restart (NPVPN-1779), None до первого коннекта.
        self.inbound_tags: set[str] | None = None

    def _recreate_session(self):
        try:
            self.session.close()
        except Exception:
            pass
        self.session = requests.Session()
        self.session.mount("https://", SANIgnoringAdaptor())
        self.session.cert = (self._certfile.name, self._keyfile.name)

    def _discard_grpc_api_unlocked(self):
        self._api = None

    def _close_grpc_api_unlocked(self):
        api = self._api
        self._api = None
        if api is None:
            return
        _safe_close_grpc_channel(getattr(api, "_channel", None))

    def _close_grpc_api(self):
        with self._grpc_lock:
            self._close_grpc_api_unlocked()

    @staticmethod
    def _close_temp_file(file_obj):
        if file_obj is None:
            return
        try:
            file_obj.close()
        except Exception:
            pass

    def _reset_local_state(self, recreate_session: bool = True, close_grpc: bool = False):
        with self._grpc_lock:
            if close_grpc:
                self._close_grpc_api_unlocked()
            else:
                self._discard_grpc_api_unlocked()
        self._close_temp_file(getattr(self, "_node_certfile", None))
        self._node_certfile = None
        self._session_id = None
        self._started = False
        if recreate_session:
            self._recreate_session()

    def _prepare_config(self, config: XRayConfig):
        return inline_local_certificates(config)

    def make_request(self, path: str, timeout: int, **params):
        try:
            req_timeout = max(1, int(timeout))
            connect_timeout = min(10, req_timeout)
            res = self.session.post(
                self._rest_api_url + path,
                timeout=(connect_timeout, req_timeout),
                json={"session_id": self._session_id, **params},
            )
            data = res.json()
        except Exception as e:
            exc = NodeAPIError(0, str(e))
            raise exc

        if res.status_code == 200:
            return data
        else:
            exc = NodeAPIError(res.status_code, data["detail"])
            raise exc

    @property
    def connected(self):
        if not self._session_id:
            return False
        try:
            self.make_request("/ping", timeout=XRAY_NODE_REST_PING_TIMEOUT)
            return True
        except NodeAPIError:
            self._reset_local_state()
            return False

    @property
    def started(self):
        res = self.make_request("/", timeout=XRAY_NODE_REST_INFO_TIMEOUT)
        remote_started = res.get("started", False)
        self._started = remote_started
        if not remote_started:
            self._close_grpc_api()
        return remote_started

    @property
    def api(self):
        if not self._session_id:
            raise ConnectionError("Node is not connected")

        if not self._api:
            if self._started is True:
                self._api = XRayAPI(
                    address=self.address,
                    port=self.api_port,
                    ssl_cert=self._node_cert.encode(),
                    ssl_target_name="Gozargah",
                )
            else:
                raise ConnectionError("Node is not started")

        return self._api

    def _setup_api(self):
        new_api = wait_for_grpc_ready(
            self.address,
            self.api_port,
            self._node_cert.encode(),
        )
        with self._grpc_lock:
            self._discard_grpc_api_unlocked()
            self._api = new_api

    def connect(self):
        if self._session_id:
            try:
                self.make_request("/disconnect", timeout=XRAY_NODE_REST_DISCONNECT_TIMEOUT)
            except NodeAPIError:
                pass
        self._reset_local_state()

        self._close_temp_file(getattr(self, "_node_certfile", None))
        self._node_cert = fetch_server_certificate(self.address, self.port, XRAY_NODE_CERT_FETCH_TIMEOUT)
        self._node_certfile = string_to_temp_file(self._node_cert)
        self.session.verify = self._node_certfile.name

        res = self.make_request("/connect", timeout=XRAY_NODE_REST_CONNECT_TIMEOUT)
        self._session_id = res["session_id"]

    def disconnect(self):
        try:
            if self._session_id:
                self.make_request("/disconnect", timeout=XRAY_NODE_REST_DISCONNECT_TIMEOUT)
        except NodeAPIError:
            pass
        finally:
            self._reset_local_state(close_grpc=True)

    def get_version(self):
        res = self.make_request("/", timeout=XRAY_NODE_REST_INFO_TIMEOUT)
        return res.get("core_version")

    def start(self, config: XRayConfig = None, *, config_json: str | None = None):
        if not self._session_id:
            self.connect()
        else:
            try:
                self.make_request("/ping", timeout=XRAY_NODE_REST_PING_TIMEOUT)
            except NodeAPIError:
                self.connect()

        try:
            info = self.make_request("/", timeout=XRAY_NODE_REST_INFO_TIMEOUT)
            if info.get("started"):
                self._started = True
                self._setup_api()
                return info
        except NodeAPIError:
            pass

        if config_json is None:
            assert config is not None, "start() requires either config or config_json"
            config = self._prepare_config(config)
            config_json = config.to_json()

        try:
            res = self.make_request("/start", timeout=XRAY_NODE_REST_START_TIMEOUT, config=config_json)
        except NodeAPIError as exc:
            if exc.detail == "Xray is started already":
                self._started = True
                self._setup_api()
                return {"started": True}
            else:
                raise exc

        self._started = True
        self._setup_api()

        return res

    def stop(self):
        if not self.connected:
            self.connect()

        self.make_request("/stop", timeout=XRAY_NODE_REST_STOP_TIMEOUT)
        self._close_grpc_api()
        self._started = False

    def restart(self, config: XRayConfig = None, *, config_json: str | None = None):
        if not self.connected:
            self.connect()

        if config_json is None:
            assert config is not None, "restart() requires either config or config_json"
            config = self._prepare_config(config)
            config_json = config.to_json()

        res = self.make_request("/restart", timeout=XRAY_NODE_REST_RESTART_TIMEOUT, config=config_json)

        self._started = True
        self._setup_api()

        return res

    def _bg_fetch_logs(self):
        while self._logs_queues:
            try:
                websocket_url = f"{self._logs_ws_url}?session_id={self._session_id}&interval=0.7"
                self._ssl_context.load_verify_locations(self.session.verify)
                ws = create_connection(websocket_url, sslopt={"context": self._ssl_context}, timeout=2)
                while self._logs_queues:
                    try:
                        logs = ws.recv()
                        for buf in self._logs_queues:
                            buf.append(logs)
                    except WebSocketConnectionClosedException:
                        break
                    except WebSocketTimeoutException:
                        pass
                    except Exception:
                        pass
            except Exception:
                pass
            time.sleep(2)

    @contextmanager
    def get_logs(self):
        try:
            buf = deque(maxlen=100)
            self._logs_queues.append(buf)

            if not self._logs_bg_thread.is_alive():
                try:
                    self._logs_bg_thread.start()
                except RuntimeError:
                    self._logs_bg_thread = threading.Thread(target=self._bg_fetch_logs, daemon=True)
                    self._logs_bg_thread.start()

            yield buf

        finally:
            try:
                self._logs_queues.remove(buf)
            except ValueError:
                pass
            del buf


class RPyCXRayNode:
    def __init__(
        self, address: str, port: int, api_port: int, ssl_key: str, ssl_cert: str, usage_coefficient: float = 1
    ):

        class Service(rpyc.Service):
            def __init__(self, on_start_funcs: list[callable] = [], on_stop_funcs: list[callable] = []):
                self.on_start_funcs = on_start_funcs
                self.on_stop_funcs = on_stop_funcs

            def exposed_on_start(self):
                for func in self.on_start_funcs:
                    threading.Thread(target=func).start()

            def exposed_on_stop(self):
                for func in self.on_stop_funcs:
                    threading.Thread(target=func).start()

            def add_startup_func(self, func):
                self.on_start_funcs.append(func)

            def add_shutdown_func(self, func):
                self.on_stop_funcs.append(func)

            def on_connect(self, conn):
                pass

            def on_disconnect(self, conn):
                pass

        self.address = address
        self.port = port
        self.api_port = api_port
        self.ssl_key = ssl_key
        self.ssl_cert = ssl_cert
        self.usage_coefficient = usage_coefficient

        self.started = False

        self._keyfile = string_to_temp_file(ssl_key)
        self._certfile = string_to_temp_file(ssl_cert)

        self._service = Service()
        self._api = None

        # Реальный набор тегов инбаундов ноды; заполняется после успешного
        # start/restart (NPVPN-1779), None до первого коннекта.
        self.inbound_tags: set[str] | None = None

    def disconnect(self):
        try:
            self.connection.close()
            del self.connection
        except AttributeError:
            pass

    def connect(self):
        self.disconnect()

        tries = 0
        while True:
            tries += 1
            self._node_cert = fetch_server_certificate(self.address, self.port, XRAY_NODE_CERT_FETCH_TIMEOUT)
            self._node_certfile = string_to_temp_file(self._node_cert)
            conn = rpyc.ssl_connect(
                self.address,
                self.port,
                service=self._service,
                keyfile=self._keyfile.name,
                certfile=self._certfile.name,
                ca_certs=self._node_certfile.name,
                keepalive=True,
            )
            try:
                conn.ping()
                self.connection = conn
                break
            except EOFError as exc:
                if tries <= 3:
                    continue
                raise exc

    @property
    def connected(self):
        try:
            self.connection.ping()
            return not self.connection.closed
        except (AttributeError, EOFError, TimeoutError):
            self.disconnect()
            return False

    @property
    def remote(self):
        if not self.connected:
            self.connect()
        return self.connection.root

    @property
    def api(self):
        if not self.connected:
            raise ConnectionError("Node is not connected")

        if not self.started:
            raise ConnectionError("Node is not started")

        return self._api

    def get_version(self):
        return self.remote.fetch_xray_version()

    def _prepare_config(self, config: XRayConfig):
        return inline_local_certificates(config)

    def start(self, config: XRayConfig = None, *, config_json: str | None = None):
        if config_json is None:
            assert config is not None, "start() requires either config or config_json"
            config = self._prepare_config(config)
            config_json = config.to_json()
        self.remote.start(config_json)
        self.started = True

        # connect to API
        try:
            self._api = wait_for_grpc_ready(
                self.address,
                self.api_port,
                self._node_cert.encode(),
            )
        except ConnectionError:
            start_time = time.time()
            end_time = start_time + 3  # check logs for 3 seconds
            last_log = ""
            with self.get_logs() as logs:
                while time.time() < end_time:
                    if logs:
                        last_log = logs[-1].strip().split("\n")[-1]
                    time.sleep(0.1)

            self.disconnect()

            if re.search(r"[Ff]ailed", last_log):
                raise RuntimeError(last_log)

            raise ConnectionError("Failed to connect to node's API")

    def stop(self):
        self.remote.stop()
        self.started = False
        self._api = None

    def restart(self, config: XRayConfig = None, *, config_json: str | None = None):
        self.started = False
        if config_json is None:
            assert config is not None, "restart() requires either config or config_json"
            config = self._prepare_config(config)
            config_json = config.to_json()
        self.remote.restart(config_json)
        self.started = True

    @contextmanager
    def get_logs(self):
        if not self.connected:
            raise ConnectionError("Node is not connected")

        try:
            self.__curr_logs
        except AttributeError:
            self.__curr_logs = 0

        try:
            buf = deque(maxlen=100)

            if self.__curr_logs <= 0:
                self.__curr_logs = 1
                self.__bgsrv = rpyc.BgServingThread(self.connection)
            else:
                if not self.__bgsrv._active:
                    self.__bgsrv = rpyc.BgServingThread(self.connection)
                self.__curr_logs += 1

            logs = self.remote.fetch_logs(buf.append)
            yield buf

        finally:
            if self.__curr_logs <= 1:
                self.__curr_logs = 0
                self.__bgsrv.stop()
            else:
                if not self.__bgsrv._active:
                    self.__bgsrv = rpyc.BgServingThread(self.connection)
                self.__curr_logs -= 1

            if logs:
                logs.stop()

    def on_start(self, func: callable):
        self._service.add_startup_func(func)
        return func

    def on_stop(self, func: callable):
        self._service.add_shutdown_func(func)
        return func


class XRayNode:
    # __new__ возвращает ReSTXRayNode/RPyCXRayNode, но для mypy это остаётся типом
    # XRayNode — атрибут нужно продублировать здесь (см. те же атрибуты в подклассах).
    inbound_tags: set[str] | None = None

    def __new__(
        self,
        address: str,
        port: int,
        api_port: int,
        ssl_key: str,
        ssl_cert: str,
        protocol: NodeProtocol = NodeProtocol.rest,
        usage_coefficient: float = 1,
    ):
        if protocol == NodeProtocol.rest or protocol == NodeProtocol.rest.value:
            return ReSTXRayNode(
                address=address,
                port=port,
                api_port=api_port,
                ssl_key=ssl_key,
                ssl_cert=ssl_cert,
                usage_coefficient=usage_coefficient,
            )

        if protocol == NodeProtocol.rpyc or protocol == NodeProtocol.rpyc.value:
            return RPyCXRayNode(
                address=address,
                port=port,
                api_port=api_port,
                ssl_key=ssl_key,
                ssl_cert=ssl_cert,
                usage_coefficient=usage_coefficient,
            )

        raise ValueError(f"Unsupported node protocol: {protocol}")
