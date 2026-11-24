"""الأرشفة الفورية لأي رابط: نسخة الصفحة كما وصلت ونصها وبصمتها SHA-256، ولقطة كاملة إن توفّر متصفح،
وطلب اختياري لحفظها في Wayback Machine (يرسل الرابط إلى جهة خارجية، فهو مطفأ ما لم يُطلب)."""

from __future__ import annotations

import hashlib
import os
import re

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from marsad.core.paths import ensure_storage
from marsad.db import utcnow
from marsad.models import User
from marsad.models.tools import Snapshot

URL_RE = re.compile(r"https?://[^\s<>\"'\])]+")


def wayback_base() -> str:
    return os.environ.get("MARSAD_WAYBACK_API", "https://web.archive.org").rstrip("/")


def _screenshot(url: str) -> bytes | None:
    """لقطة كاملة للصفحة بمتصفح Playwright إن كان مثبّتًا (على الخادم وفي التطوير). على الجهاز قد لا يتوفر."""
    if os.environ.get("MARSAD_SNAPSHOT_SCREENSHOT", "1") == "0":
        return None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1280, "height": 900})
            pg.goto(url, wait_until="load", timeout=30000)
            raw = pg.screenshot(full_page=True)
            b.close()
            return raw
    except Exception:  # noqa: BLE001 — أي تعذّر في اللقطة لا يُفشل الأرشفة
        return None


def _wayback(url: str) -> tuple[str, str]:
    try:
        r = httpx.get(f"{wayback_base()}/save/{url}", timeout=60, follow_redirects=True)
    except httpx.HTTPError as e:
        return "failed", f"تعذّر الاتصال: {e.__class__.__name__}"
    loc = r.headers.get("content-location") or ""
    if r.status_code < 400:
        return "ok", (f"{wayback_base()}{loc}" if loc.startswith("/") else str(r.url))
    return "failed", f"رفض الطلب ({r.status_code})"


def archive(db: Session, user: User | None, url: str, *, wayback: bool = False, claim_id: int | None = None,
            case_id: int | None = None) -> Snapshot:
    from marsad.monitor.fetch import FetchError, get
    from marsad.monitor.service import extract

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("الرابط يبدأ بـ http أو https")
    now = utcnow()
    s = Snapshot(url=url[:1000], status="ok", error="", wayback_status="", wayback_url="", claim_id=claim_id, case_id=case_id, created_by=user.id if user else None, created_at=now)
    try:
        r = get(url, check_robots=False)  # رابط يضعه الصحفي بنفسه للأرشفة، لا زحف
        raw = r.content
        s.http_status, s.final_url = r.status_code, str(r.url)[:1000]
        s.sha256 = hashlib.sha256(raw).hexdigest()
        root = ensure_storage().archive
        rel = f"snapshots/{now:%Y/%m}/{s.sha256}.html"
        p = root / rel
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(raw)
        s.html_path = rel
        if "html" in (r.headers.get("content-type") or "html"):
            ex = extract(raw, url)
            s.title, s.text = ex["title"][:2000], ex["text"]
        shot = _screenshot(url)
        if shot:
            sh = hashlib.sha256(shot).hexdigest()
            srel = f"snapshots/{now:%Y/%m}/{sh}.png"
            (root / srel).write_bytes(shot)
            s.screenshot_path, s.screenshot_sha256 = srel, sh
    except FetchError as e:
        s.status, s.error = "error", str(e)
    if wayback and s.status == "ok":
        s.wayback_status, s.wayback_url = _wayback(url)
        if s.wayback_status == "failed":
            s.error, s.wayback_url = s.wayback_url, ""
    elif not wayback:
        s.wayback_status = "off"
    db.add(s)
    db.flush()
    return s


def archive_links_in(db: Session, user: User | None, text: str, case_id: int, limit: int = 10) -> list[Snapshot]:
    """يؤرشف الروابط المستشهد بها في مسودة قصة، ما لم تُؤرشف لهذه القضية من قبل."""
    done = set(db.scalars(select(Snapshot.url).where(Snapshot.case_id == case_id, Snapshot.status == "ok")).all())
    out = []
    for u in list(dict.fromkeys(m.rstrip(".,،؛") for m in URL_RE.findall(text or "")))[:limit]:
        if u not in done:
            out.append(archive(db, user, u, case_id=case_id))
    return out


def view(s: Snapshot) -> dict:
    return {"id": s.id, "url": s.url, "final_url": s.final_url, "title": s.title, "sha256": s.sha256, "status": s.status,
            "error": s.error, "http_status": s.http_status, "has_screenshot": bool(s.screenshot_path),
            "screenshot_sha256": s.screenshot_sha256, "wayback_status": s.wayback_status, "wayback_url": s.wayback_url,
            "claim_id": s.claim_id, "case_id": s.case_id, "created_at": s.created_at.isoformat(),
            "text_preview": (s.text or "")[:600]}
