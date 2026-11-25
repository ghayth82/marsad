"""المحرك المحلي المجاني: نماذج مفتوحة تعمل على الجهاز عبر llama.cpp (llama-server)، دون إنترنت ودون أن يخرج النص.

- القائمة: local_models.json؛ البصمات ونسخ غيث على Hugging Face: models.lock.json.
- التنزيل: من نسخة غيث فقط، مستأنَف إن انقطع، ويُرفض الملف إن اختلفت بصمته.
- التشغيل: نموذج واحد محمّل في الذاكرة؛ طلب نموذج آخر يُنزل الأول ويحمّل الثاني.
- كشف الجهاز (الذاكرة، بطاقة الرسوم، المساحة) للعرض فقط: لا يمنع تنزيل أي نموذج.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
HERE = Path(__file__).parent
HF = "https://huggingface.co"


class LocalError(RuntimeError):
    pass


# ------------------------------------------------------------------ القائمة

def catalog() -> list[dict]:
    models = json.loads((HERE / "local_models.json").read_text(encoding="utf-8"))["models"]
    lock = lock_data()
    for m in models:
        m["mirrored"] = m["id"] in lock
    return models


def lock_data() -> dict:
    p = HERE / "models.lock.json"
    return json.loads(p.read_text(encoding="utf-8")).get("models", {}) if p.exists() else {}


def get(mid: str) -> dict:
    m = next((x for x in catalog() if x["id"] == mid), None)
    if not m:
        raise LocalError("نموذج غير موجود في القائمة")
    return m


def models_dir() -> Path:
    from marsad.core.paths import ensure_storage

    return ensure_storage().models


def path_of(m: dict) -> Path:
    return models_dir() / m["file"]


def installed(m: dict) -> bool:
    p = path_of(m)
    ok = p.with_name(p.name + ".verified")
    return p.exists() and ok.exists() and ok.read_text().strip() == lock_data().get(m["id"], {}).get("sha256", "")


# ------------------------------------------------------------------ الجهاز

def _run(cmd: list[str], timeout: int = 8) -> str:
    try:
        kw = {"creationflags": 0x08000000} if os.name == "nt" else {}  # دون نافذة سوداء على ويندوز
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _ram_gb() -> float:
    if os.name == "nt":
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong), ("a", ctypes.c_ulonglong), ("b", ctypes.c_ulonglong),
                        ("c", ctypes.c_ulonglong), ("d", ctypes.c_ulonglong), ("e", ctypes.c_ulonglong)]
        s = MS()
        s.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(s))
        return round(s.ullTotalPhys / 2**30, 1)
    try:
        kb = int(re.search(r"MemTotal:\s+(\d+)", Path("/proc/meminfo").read_text()).group(1))
        return round(kb / 2**20, 1)
    except (OSError, AttributeError):
        return 0.0


def _gpus() -> list[dict]:
    out: list[dict] = []
    smi = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    for line in smi.splitlines():
        if "," in line:
            name, mem = line.rsplit(",", 1)
            out.append({"name": name.strip(), "vram_gb": round(float(mem) / 1024, 1)})
    if out or os.name != "nt":
        return out
    # ويندوز دون NVIDIA: الاسم من WMI والذاكرة من السجل (WMI يقف عند 4 غيغابايت)
    ps = ("$r=@(); Get-ItemProperty 'HKLM:\\SYSTEM\\ControlSet001\\Control\\Class\\{4d36e968-e325-11ce-bfc1-08002be10318}\\0*' "
          "-ErrorAction SilentlyContinue | ForEach-Object { if ($_.DriverDesc) { $r += \"$($_.DriverDesc)|$($_.'HardwareInformation.qwMemorySize')\" } }; $r")
    for line in _run(["powershell", "-NoProfile", "-Command", ps], timeout=15).splitlines():
        if "|" in line:
            name, mem = line.split("|", 1)
            vram = round(int(mem) / 2**30, 1) if mem.strip().isdigit() else 0.0
            if name.strip() and "Basic Display" not in name:
                out.append({"name": name.strip(), "vram_gb": vram})
    return out


_HW: dict | None = None


def hardware(refresh: bool = False) -> dict:
    global _HW
    if _HW is None or refresh:
        gpus = _gpus()
        _HW = {"ram_gb": _ram_gb(), "gpus": gpus, "vram_gb": max((g["vram_gb"] for g in gpus), default=0.0),
               "cpu": platform.processor() or platform.machine(), "cores": os.cpu_count() or 0, "os": platform.system()}
    try:
        _HW["disk_free_gb"] = round(shutil.disk_usage(models_dir()).free / 2**30, 1)
    except OSError:
        _HW["disk_free_gb"] = 0.0
    _HW["runtime"] = bool(server_binary())
    return _HW


def fit(m: dict, hw: dict) -> dict:
    """للعرض فقط: كيف سيعمل النموذج على هذا الجهاز. لا يمنع التنزيل."""
    disk_ok = hw.get("disk_free_gb", 0) >= m["size_gb"] + 1 or installed(m)
    if hw.get("vram_gb", 0) >= m["vram_gb"]:
        level, text = "fast", "يعمل بسرعة على بطاقة الرسوم في هذا الجهاز"
    elif hw.get("ram_gb", 0) >= m["ram_gb"]:
        level, text = "ok", "يعمل على هذا الجهاز بالمعالج والذاكرة، أبطأ من بطاقة الرسوم"
    else:
        level, text = "heavy", f"ثقيل على هذا الجهاز: يحتاج نحو {m['ram_gb']} غيغابايت ذاكرة (المتاح {hw.get('ram_gb', 0)})"
    if not disk_ok:
        text += f". المساحة الحرة ({hw.get('disk_free_gb', 0)} غيغابايت) لا تكفي لتنزيله ({m['size_gb']} غيغابايت)"
    return {"level": level, "text": text, "disk_ok": disk_ok}


# ------------------------------------------------------------------ التنزيل

_DL: dict[str, dict] = {}
_DL_LOCK = threading.Lock()


def download_state(mid: str) -> dict:
    return dict(_DL.get(mid, {}))


def start_download(mid: str) -> dict:
    m = get(mid)
    lk = lock_data().get(mid)
    if not lk:
        raise LocalError("لم يُنسخ هذا النموذج إلى حسابك بعد؛ شغّل mirror-models على GitHub ثم حدّث البرنامج")
    with _DL_LOCK:
        if _DL.get(mid, {}).get("status") in ("downloading", "verifying"):
            return download_state(mid)
        _DL[mid] = {"status": "downloading", "done": 0, "total": lk["bytes"], "error": "", "cancel": False}
    threading.Thread(target=_download, args=(m, lk), name=f"dl-{mid}", daemon=True).start()
    return download_state(mid)


def cancel_download(mid: str) -> None:
    if mid in _DL:
        _DL[mid]["cancel"] = True


def _download(m: dict, lk: dict) -> None:
    st = _DL[m["id"]]
    dest = path_of(m)
    part = dest.with_name(dest.name + ".part")
    url = f"{HF}/{lk['mirror']}/resolve/main/{lk['file']}"
    try:
        for attempt in range(5):  # يُستأنف من حيث توقف إن انقطع الاتصال
            have = part.stat().st_size if part.exists() else 0
            st["done"] = have
            if have >= lk["bytes"]:
                break
            try:
                with httpx.stream("GET", url, headers={"Range": f"bytes={have}-"} if have else {},
                                  follow_redirects=True, timeout=httpx.Timeout(60, connect=20)) as r:
                    if r.status_code not in (200, 206):
                        raise LocalError(f"تعذّر التنزيل من النسخة ({r.status_code})")
                    if r.status_code == 200 and have:
                        part.unlink()  # الخادم لا يدعم الاستئناف: نبدأ من جديد
                        st["done"] = 0
                    with part.open("ab") as f:
                        for chunk in r.iter_bytes(1 << 20):
                            if st["cancel"]:
                                st["status"] = "cancelled"
                                return
                            f.write(chunk)
                            st["done"] += len(chunk)
                break
            except (httpx.HTTPError, OSError) as e:
                if attempt == 4:
                    raise LocalError(f"انقطع التنزيل: {e}") from None
                time.sleep(3 * (attempt + 1))
        st["status"] = "verifying"
        h = hashlib.sha256()
        with part.open("rb") as f:
            for chunk in iter(lambda: f.read(8 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != lk["sha256"]:
            part.unlink(missing_ok=True)
            raise LocalError("بصمة الملف المنزَّل لا تطابق نسختك؛ حُذف ولم يُستعمل")
        part.replace(dest)
        dest.with_name(dest.name + ".verified").write_text(lk["sha256"])
        st["status"] = "done"
    except LocalError as e:
        st.update(status="error", error=str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("فشل تنزيل %s", m["id"])
        st.update(status="error", error=f"خطأ غير متوقع: {e}")


def remove(mid: str) -> None:
    m = get(mid)
    if RUNNER.current == mid:
        RUNNER.stop()
    p = path_of(m)
    for f in (p, p.with_name(p.name + ".verified"), p.with_name(p.name + ".part")):
        f.unlink(missing_ok=True)
    _DL.pop(mid, None)


# ------------------------------------------------------------------ التشغيل

def server_binary() -> str | None:
    return os.environ.get("MARSAD_LLAMA_SERVER") or shutil.which("llama-server")


class Runner:
    """يُبقي نموذجًا واحدًا محمّلًا في llama-server؛ طلب نموذج آخر يُبدّل بينهما."""

    def __init__(self) -> None:
        self.proc: subprocess.Popen | None = None
        self.current: str | None = None
        self.port = 0
        self.lock = threading.Lock()

    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def ensure(self, mid: str) -> str:
        with self.lock:
            if self.current == mid and self.proc and self.proc.poll() is None:
                return self.base_url()
            m = get(mid)
            if not installed(m):
                raise LocalError(f"النموذج «{m['name']}» غير منزَّل؛ نزّله من «المحركات» أولًا")
            exe = server_binary()
            if not exe:
                raise LocalError("المحرك المحلي (llama.cpp) غير مضمّن في هذه النسخة من البرنامج")
            self.stop()
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                self.port = s.getsockname()[1]
            cmd = [exe, "-m", str(path_of(m)), "--host", "127.0.0.1", "--port", str(self.port),
                   "-c", str(min(m.get("context", 8192), 16384)), "-ngl", "999", "--jinja"]
            kw = {"creationflags": 0x08000000} if os.name == "nt" else {}
            self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
            self.current = mid
            deadline = time.time() + 300  # تحميل نموذج كبير من القرص قد يستغرق دقائق
            while time.time() < deadline:
                if self.proc.poll() is not None:
                    self.current = None
                    raise LocalError("توقف المحرك المحلي أثناء تحميل النموذج (قد لا تكفي الذاكرة)")
                try:
                    if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                        return self.base_url()
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            self.stop()
            raise LocalError("استغرق تحميل النموذج وقتًا طويلًا")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc, self.current = None, None


RUNNER = Runner()
atexit.register(RUNNER.stop)
