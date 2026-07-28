import copy
import json
import threading
import time

from app.xray.node_config import (
    _NodeJsonCache,
    build_node_config_json,
    node_config_json,
    node_signature,
)

# --- FakeConfig: мимикрия XRayConfig (dict + copy(deep) + inbounds_by_tag + to_json) ---
INBOUNDS = [
    {"tag": "API_INBOUND", "protocol": "dokodemo-door"},
    {
        "tag": "VLESS_TCP",
        "protocol": "vless",
        "settings": {
            "clients": [
                {"email": "1.alice", "id": "u1"},
                {"email": "2.bob", "id": "u2"},
            ]
        },
    },
]
MANAGED = {"VLESS_TCP"}


class FakeConfig(dict):
    def __init__(self, *args, inbounds_by_tag=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._inbounds_by_tag = inbounds_by_tag or {}

    @property
    def inbounds_by_tag(self):
        return self._inbounds_by_tag

    def copy(self):
        clone = FakeConfig(inbounds_by_tag=self._inbounds_by_tag)
        clone["inbounds"] = [
            {**i, "settings": {**i.get("settings", {}), "clients": list((i.get("settings") or {}).get("clients", []))}}
            if i.get("settings")
            else dict(i)
            for i in self["inbounds"]
        ]
        clone["outbounds"] = [dict(o) for o in self.get("outbounds", [])]
        return clone

    def to_json(self, **kw):
        return json.dumps({"inbounds": self["inbounds"], "outbounds": self.get("outbounds", [])}, sort_keys=True, **kw)


def _base():
    return FakeConfig(
        {"inbounds": [dict(i) for i in INBOUNDS], "outbounds": [{"tag": "direct"}]},
        inbounds_by_tag={"VLESS_TCP": {}},
    )


class NoCacheAttrConfig(FakeConfig):
    """Мимикрия объекта, который не может держать доп. атрибуты: setattr для
    _node_json_cache бросает AttributeError (остальные атрибуты, включая служебные,
    выставляемые в __init__ родителя, работают как обычно)."""

    def __setattr__(self, name, value):
        if name == "_node_json_cache":
            raise AttributeError("no cache slot")
        super().__setattr__(name, value)


class DeepCopyConfig(FakeConfig):
    """В отличие от FakeConfig.copy() (вручную пересобирает dict, теряя произвольные
    атрибуты), здесь copy() == copy.deepcopy(self) — как в настоящем XRayConfig.copy()
    (app/xray/config.py). Нужен, чтобы регрессионный тест реально гонял deepcopy по
    навешанному _node_json_cache и ловил TypeError на threading.Lock, а не проходил
    мимо бага, как это делает FakeConfig."""

    def copy(self):
        return copy.deepcopy(self)


def test_signature_is_order_independent():
    a = node_signature(["B", "A"], {"role": "direct"}, [2, 1])
    b = node_signature(["A", "B"], {"role": "direct"}, [1, 2])
    assert a == b


def test_signature_differs_on_cascade():
    direct = node_signature([], {"role": "direct"}, [])
    entry = node_signature([], {"role": "entry", "entry_routes": [{"x": 1}]}, [])
    assert direct != entry


def test_signature_handles_none():
    assert node_signature(None, {"role": "direct"}, None) == ((), json.dumps({"role": "direct"}, sort_keys=True), ())


def test_build_direct_serializes_all_clients():
    js = build_node_config_json(_base(), [], {"role": "direct"}, [])
    data = json.loads(js)
    vless = next(i for i in data["inbounds"] if i["tag"] == "VLESS_TCP")
    assert {c["email"] for c in vless["settings"]["clients"]} == {"1.alice", "2.bob"}


def test_build_strips_blocked_user():
    js = build_node_config_json(_base(), [], {"role": "direct"}, [1])
    data = json.loads(js)
    vless = next(i for i in data["inbounds"] if i["tag"] == "VLESS_TCP")
    assert {c["email"] for c in vless["settings"]["clients"]} == {"2.bob"}


def test_build_filters_inbounds_by_tags():
    # tags=["NOPE"] → остаётся только инфраструктурный API_INBOUND
    js = build_node_config_json(_base(), ["NOPE"], {"role": "direct"}, [])
    data = json.loads(js)
    assert [i["tag"] for i in data["inbounds"]] == ["API_INBOUND"]


def _counting_build_factory():
    calls = []

    def build(base, tags, cascade_kwargs, blocked):
        calls.append(node_signature(tags, cascade_kwargs, blocked))
        # уникальная строка на сигнатуру, чтобы отличать значения
        return json.dumps({"sig": len(set(calls))})

    return build, calls


def test_cache_hit_builds_once_per_signature():
    build, calls = _counting_build_factory()
    cache = _NodeJsonCache(_base(), build=build)
    for _ in range(5):
        cache.get([], {"role": "direct"}, [])
    assert cache.build_count == 1
    assert len(calls) == 1


def test_cache_different_signatures_build_separately():
    build, calls = _counting_build_factory()
    cache = _NodeJsonCache(_base(), build=build)
    cache.get([], {"role": "direct"}, [])
    cache.get(["VLESS_TCP"], {"role": "direct"}, [])
    cache.get([], {"role": "direct"}, [1])
    assert cache.build_count == 3


def test_cache_returns_identical_string_on_hit():
    cache = _NodeJsonCache(_base())
    a = cache.get([], {"role": "direct"}, [])
    b = cache.get([], {"role": "direct"}, [])
    assert a == b


def test_cache_thread_safe_single_build():
    # Лок в _NodeJsonCache.get() сериализует "check+build+store" целиком, поэтому билд
    # под одну сигнатуру физически не может произойти дважды даже под реальной гонкой
    # потоков. small sleep внутри build() расширяет окно гонки: пока первый поток строит
    # конфиг, остальные 7 успевают упереться в захват лока и после его освобождения
    # получить уже готовое значение из кэша, а не запустить билд повторно.
    def slow_build(base, tags, cascade_kwargs, blocked):
        time.sleep(0.05)
        return json.dumps({"ok": True})

    cache = _NodeJsonCache(_base(), build=slow_build)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker():
        r = cache.get([], {"role": "direct"}, [])
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert cache.build_count == 1
    assert len(results) == 8
    assert len(set(results)) == 1


def test_node_config_json_reuses_cache_on_config_object():
    base = _base()
    a = node_config_json(base, [], {"role": "direct"}, [])
    assert hasattr(base, "_node_json_cache")
    b = node_config_json(base, [], {"role": "direct"}, [])
    assert a == b
    assert base._node_json_cache.build_count == 1


def test_node_config_json_lazy_creation_thread_safe(monkeypatch):
    # Регрессионный тест на double-checked locking в node_config_json: без _attach_lock
    # N потоков, увидевших отсутствие base._node_json_cache одновременно, создали бы
    # каждый свой _NodeJsonCache и билдили бы независимо. Барьер сводит все N вызовов
    # node_config_json к одному моменту старта, максимизируя шанс реальной гонки на
    # незалоченной проверке getattr(...) перед входом в _attach_lock.
    import app.xray.node_config as node_config_module

    created: list[int] = []
    created_lock = threading.Lock()
    real_cache_cls = node_config_module._NodeJsonCache

    class CountingCache(real_cache_cls):
        def __init__(self, *args, **kwargs):
            with created_lock:
                created.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(node_config_module, "_NodeJsonCache", CountingCache)

    base = _base()
    n = 32
    barrier = threading.Barrier(n)
    results: list[str] = []
    results_lock = threading.Lock()

    def worker():
        barrier.wait()
        r = node_config_json(base, [], {"role": "direct"}, [])
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(created) == 1  # ровно один _NodeJsonCache сконструирован
    assert hasattr(base, "_node_json_cache")
    assert base._node_json_cache.build_count == 1  # ровно один build на сигнатуру
    assert len(results) == n
    assert len(set(results)) == 1  # все потоки получили одну и ту же строку


def test_node_config_json_falls_back_when_attribute_rejected():
    # Minor: объект не может держать _node_json_cache (setattr бросает) — фасад не
    # должен падать, а должен деградировать до билда без шаринга кэша.
    base = NoCacheAttrConfig(
        {"inbounds": [dict(i) for i in INBOUNDS], "outbounds": [{"tag": "direct"}]},
        inbounds_by_tag={"VLESS_TCP": {}},
    )
    js = node_config_json(base, [], {"role": "direct"}, [])
    data = json.loads(js)
    vless = next(i for i in data["inbounds"] if i["tag"] == "VLESS_TCP")
    assert {c["email"] for c in vless["settings"]["clients"]} == {"1.alice", "2.bob"}
    assert not hasattr(base, "_node_json_cache")

    # повторный вызов тоже не падает и строит корректный конфиг (каждый раз заново)
    js2 = node_config_json(base, [], {"role": "direct"}, [])
    assert js2 == js


from app.xray.node_config import inline_local_certificates


def test_real_deepcopy_config_with_cache_survives_copy():
    """Регрессия NPVPN-1727: XRayConfig.copy() == deepcopy(self) (app/xray/config.py).
    include_db_users() вешает _NodeJsonCache (с threading.Lock внутри) на волновой
    конфиг; build_node_config_json зовёт base_config.copy() для любой ноды с непустыми
    тегами, cascade-ролью entry/exit или заблокированными пользователями. Без
    _NodeJsonCache.__deepcopy__ это падает с `TypeError: cannot pickle
    '_thread.lock' object`, и такие ноды никогда не подключаются."""
    base = DeepCopyConfig(
        {"inbounds": [dict(i) for i in INBOUNDS], "outbounds": [{"tag": "direct"}]},
        inbounds_by_tag={"VLESS_TCP": {}},
    )
    base._node_json_cache = _NodeJsonCache(base)

    # Прямая гарантия фикса: deepcopy конфига с кэшем не должен падать на Lock.
    cloned = copy.deepcopy(base)
    assert isinstance(cloned, DeepCopyConfig)

    # Реальный путь сборки: непустые теги (apply_inbound_filter → .copy()) и
    # заблокированный пользователь (strip_blocked_clients → .copy()) — вместе
    # заставляют build_node_config_json дважды пройти через base_config.copy().
    js = build_node_config_json(base, ["VLESS_TCP"], {"role": "direct"}, [1])
    data = json.loads(js)
    assert {i["tag"] for i in data["inbounds"]} == {"API_INBOUND", "VLESS_TCP"}
    vless = next(i for i in data["inbounds"] if i["tag"] == "VLESS_TCP")
    assert {c["email"] for c in vless["settings"]["clients"]} == {"2.bob"}


def _cert_config(tmp_path):
    cert = tmp_path / "fullchain.pem"
    key = tmp_path / "privkey.pem"
    cert.write_text("CERT-LINE-1\nCERT-LINE-2\n")
    key.write_text("KEY-LINE-1\n")
    return {
        "inbounds": [
            {
                "tag": "VLESS_TLS",
                "streamSettings": {
                    "tlsSettings": {"certificates": [{"certificateFile": str(cert), "keyFile": str(key)}]}
                },
            }
        ]
    }


def test_inline_certificates_replaces_files(tmp_path):
    cfg = _cert_config(tmp_path)
    inline_local_certificates(cfg)
    c = cfg["inbounds"][0]["streamSettings"]["tlsSettings"]["certificates"][0]
    assert c["certificate"] == ["CERT-LINE-1", "CERT-LINE-2"]
    assert c["key"] == ["KEY-LINE-1"]
    assert "certificateFile" not in c
    assert "keyFile" not in c


def test_inline_certificates_idempotent(tmp_path):
    cfg = _cert_config(tmp_path)
    inline_local_certificates(cfg)
    snapshot = json.dumps(cfg, sort_keys=True)
    inline_local_certificates(cfg)  # второй проход — no-op
    assert json.dumps(cfg, sort_keys=True) == snapshot


def test_inline_certificates_no_tls_inbound_noop():
    cfg = {"inbounds": [{"tag": "PLAIN", "protocol": "vless"}]}
    inline_local_certificates(cfg)
    assert cfg == {"inbounds": [{"tag": "PLAIN", "protocol": "vless"}]}
