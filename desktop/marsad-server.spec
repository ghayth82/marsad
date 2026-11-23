# PyInstaller: يغلّف الخادم الداخلي في مجلد واحد (onedir) يُضمَّن في المُثبِّت.
# البناء: cd backend && pyinstaller ../desktop/marsad-server.spec --distpath ../desktop/build/dist --workpath ../desktop/build/work
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

backend = Path(SPECPATH).parent / "backend"
datas, binaries, hidden = [], [], []
for pkg in ("procrastinate", "psycopg", "psycopg_binary", "alembic", "argon2", "uvicorn", "cryptography", "httpx", "trafilatura", "justext", "feedparser", "lxml", "courlan", "htmldate", "dateparser", "c2pa", "PIL", "numpy", "multipart", "python_multipart"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
hidden += collect_submodules("marsad")
# ملفات الترحيلات (القالب والإصدارات) تُقرأ من القرص وقت التشغيل
datas += [(str(backend / "marsad" / "migrations"), "marsad/migrations")]

a = Analysis(
    [str(backend / "marsad" / "desktop.py")],
    pathex=[str(backend)],
    datas=datas,
    binaries=binaries,
    hiddenimports=hidden,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="marsad-server", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="marsad-server", upx=False)
