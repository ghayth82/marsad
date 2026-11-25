"""المحرك المحلي المجاني: القائمة والمتطلبات، التنزيل ببصمة، التفعيل، والتشغيل والتبديل بين النماذج."""
import hashlib
import json
import os
import stat
import sys
import textwrap
import time
from contextlib import contextmanager

import pytest

from marsad.engines import local

DATA = b"GGUF" + b"\x00" * 4096


def _wait(mid, until=("done", "error"), t=10):
    end = time.time() + t
    while time.time() < end:
        if local.download_state(mid).get("status") in until:
            return local.download_state(mid)
        time.sleep(0.05)
    raise AssertionError(local.download_state(mid))


@pytest.fixture
def fake_mirror(monkeypatch):
    """نسخة غيث على Hugging Face بديلة: ملف صغير وبصمته، دون إنترنت."""
    served = {"data": DATA}
    lock = {"qwen3.5-2b": {"id": "qwen3.5-2b", "file": "Qwen3.5-2B-Q4_K_M.gguf", "mirror": "GhaythMahadin/Qwen3.5-2B-GGUF",
                           "sha256": hashlib.sha256(DATA).hexdigest()},
            "qwen3.5-4b": {"id": "qwen3.5-4b", "file": "Qwen3.5-4B-Q4_K_M.gguf", "mirror": "GhaythMahadin/Qwen3.5-4B-GGUF",
                           "sha256": hashlib.sha256(DATA).hexdigest()}}
    monkeypatch.setattr(local, "lock_data", lambda: lock)

    class Resp:
        status_code = 200

        def __init__(self, start):
            self.start = start
            self.status_code = 206 if start else 200
            n = len(served["data"])
            self.headers = {"content-range": f"bytes {start}-{n - 1}/{n}"} if start else {"content-length": str(n)}

        def iter_bytes(self, n):
            d = served["data"][self.start:]
            for i in range(0, len(d), 1000):
                yield d[i:i + 1000]

    @contextmanager
    def stream(method, url, headers=None, **kw):
        assert url.startswith("https://huggingface.co/GhaythMahadin/")  # من نسخة غيث فقط
        start = int(headers["Range"].split("=")[1].rstrip("-")) if headers else 0
        yield Resp(start)

    monkeypatch.setattr(local.httpx, "stream", stream)
    yield served
    for mid in lock:
        local.remove(mid)


def test_catalog_shows_requirements_fit_and_provider_cards(admin):
    r = admin.get("/api/engines/catalog").json()
    assert {"ram_gb", "gpus", "disk_free_gb", "runtime"} <= set(r["hardware"])
    assert len(r["local"]) == 9
    m = next(x for x in r["local"] if x["id"] == "allam-7b")
    for k in ("size_gb", "ram_gb", "vram_gb", "license", "languages", "arabic", "strengths", "limits"):
        assert m[k], k
    assert m["fit"]["level"] in ("fast", "ok", "heavy") and m["fit"]["text"]
    for p in ("local", "anthropic", "openai", "gemini", "ollama"):
        card = r["providers"][p]
        assert card["what"] and card["needs"] and card["cost"] and card["privacy"], p
    assert "مجاني" in r["providers"]["local"]["cost"]


def test_fit_is_information_never_a_block():
    m = local.get("qwen3.6-35b-a3b")
    f = local.fit(m, {"ram_gb": 8, "vram_gb": 0, "disk_free_gb": 500})
    assert f["level"] == "heavy" and "26" in f["text"]
    assert local.fit(m, {"ram_gb": 64, "vram_gb": 24, "disk_free_gb": 500})["level"] == "fast"


def test_download_verify_activate_and_list(admin, fake_mirror):
    r = admin.post("/api/engines/local/qwen3.5-2b/download")
    assert r.status_code == 200
    assert _wait("qwen3.5-2b")["status"] == "done"
    assert local.installed(local.get("qwen3.5-2b"))
    eid = admin.post("/api/engines/local/qwen3.5-2b/activate").json()["engine_id"]
    e = next(x for x in admin.get("/api/engines").json()["engines"] if x["id"] == eid)
    assert e["provider"] == "local" and e["local"] is True
    assert admin.post("/api/engines/models", json={"provider": "local"}).json()["models"][0]["id"] == "qwen3.5-2b"
    # الحذف يحرر القرص ويعطّل المحرك، والنموذج يبقى في القائمة
    assert admin.delete("/api/engines/local/qwen3.5-2b").status_code == 200
    assert not local.installed(local.get("qwen3.5-2b"))
    assert next(x for x in admin.get("/api/engines").json()["engines"] if x["id"] == eid)["enabled"] is False


def test_tampered_file_is_rejected(admin, fake_mirror):
    fake_mirror["data"] = b"GGUF" + b"\x01" * 4096  # النسخة عُدّلت: البصمة لا تطابق
    admin.post("/api/engines/local/qwen3.5-2b/download")
    st = _wait("qwen3.5-2b")
    assert st["status"] == "error" and "بصمة" in st["error"]
    assert not local.installed(local.get("qwen3.5-2b"))
    assert not local.path_of(local.get("qwen3.5-2b")).exists()


def test_not_mirrored_yet(admin, monkeypatch):
    monkeypatch.setattr(local, "lock_data", lambda: {})
    r = admin.post("/api/engines/local/gemma-4-12b/download")
    assert r.status_code == 400 and "mirror-models" in r.json()["detail"]


FAKE_SERVER = textwrap.dedent('''
    import json, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    args = sys.argv[1:]
    model = args[args.index("-m") + 1]
    port = int(args[args.index("--port") + 1])
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def _send(self, obj):
            b = json.dumps(obj).encode(); self.send_response(200)
            self.send_header("content-type", "application/json"); self.send_header("content-length", str(len(b)))
            self.end_headers(); self.wfile.write(b)
        def do_GET(self): self._send({"status": "ok"})
        def do_POST(self):
            n = int(self.headers["content-length"]); json.loads(self.rfile.read(n))
            self._send({"choices": [{"message": {"content": "{\\"model_file\\": \\"%s\\"}" % model.replace("\\\\", "/").split("/")[-1]}}],
                        "usage": {"prompt_tokens": 5, "completion_tokens": 3}, "model": "local"})
    HTTPServer(("127.0.0.1", port), H).serve_forever()
''')


def test_runner_loads_and_switches_models(admin, fake_mirror, tmp_path, monkeypatch):
    script = tmp_path / "llama-server"
    script.write_text(f"#!{sys.executable}\n" + FAKE_SERVER)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("MARSAD_LLAMA_SERVER", str(script))
    for mid in ("qwen3.5-2b", "qwen3.5-4b"):
        admin.post(f"/api/engines/local/{mid}/download")
        assert _wait(mid)["status"] == "done"
    from marsad.engines.providers import complete

    try:
        a = complete("local", model="qwen3.5-2b", system="s", user="u", api_key=None)
        assert json.loads(a.text)["model_file"] == "Qwen3.5-2B-Q4_K_M.gguf" and local.RUNNER.current == "qwen3.5-2b"
        b = complete("local", model="qwen3.5-4b", system="s", user="u", api_key=None)  # تبديل: يُنزل الأول ويحمّل الثاني
        assert json.loads(b.text)["model_file"] == "Qwen3.5-4B-Q4_K_M.gguf" and local.RUNNER.current == "qwen3.5-4b"
        cat = {m["id"]: m for m in admin.get("/api/engines/catalog").json()["local"]}
        assert cat["qwen3.5-4b"]["loaded"] and not cat["qwen3.5-2b"]["loaded"]
        assert admin.post("/api/engines/local/unload").status_code == 200 and local.RUNNER.current is None
    finally:
        local.RUNNER.stop()


def test_no_runtime_message(fake_mirror, monkeypatch, admin):
    monkeypatch.delenv("MARSAD_LLAMA_SERVER", raising=False)
    monkeypatch.setattr(local.shutil, "which", lambda n: None)
    admin.post("/api/engines/local/qwen3.5-2b/download")
    _wait("qwen3.5-2b")
    from marsad.engines.providers import ProviderError, complete

    with pytest.raises(ProviderError, match="غير مضمّن"):
        complete("local", model="qwen3.5-2b", system="s", user="u", api_key=None)
