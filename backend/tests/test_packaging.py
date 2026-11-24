"""يضمن أن مُثبِّت ويندوز يضمّ كل ملفات البيانات التي يقرؤها الخادم (مثل قائمة المصادر المقترحة)."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"


def _spec_datas() -> list[tuple[str, str]]:
    datas: list = []
    spec = (ROOT / "desktop" / "marsad-server.spec").read_text(encoding="utf-8")
    # نشغّل جزء جمع الملفات فقط دون PyInstaller
    start = spec.index('datas += [(str(backend / "marsad" / "migrations")')
    end = spec.index("a = Analysis(")
    exec(spec[start:end], {"backend": BACKEND, "datas": datas, "Path": Path})
    return datas


def test_every_data_file_is_bundled():
    bundled = {Path(dst) / Path(src).name for src, dst in _spec_datas() if Path(src).is_file()}
    missing = [str(f.relative_to(BACKEND)) for f in (BACKEND / "marsad").rglob("*")
               if f.is_file() and f.suffix not in (".py", ".pyc") and "migrations" not in f.parts
               and "__pycache__" not in f.parts and f.relative_to(BACKEND) not in bundled]
    assert not missing, f"ملفات بيانات لا يضمّها المُثبِّت: {missing}"


def test_seed_list_is_bundled():
    if not (ROOT / "desktop" / "marsad-server.spec").exists():
        pytest.skip("لا ملف بناء")
    assert any(Path(s).name == "seed_sources.json" for s, _ in _spec_datas())
