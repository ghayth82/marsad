"""جلب الصفحات بأدب: هوية واضحة، احترام robots.txt، مهلة بين طلبات الموقع الواحد."""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

USER_AGENT = "MarsadBot/0.1 (+https://github.com/ghayth82/marsad; journalism monitoring)"
TIMEOUT = httpx.Timeout(25.0, connect=10.0)
HOST_DELAY = 1.5  # ثوانٍ بين طلبين لنفس الموقع
MAX_BYTES = 8 * 1024 * 1024

_last: dict[str, float] = {}
_robots: dict[str, tuple[float, RobotFileParser | None]] = {}
_lock = threading.Lock()


class FetchError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _throttle(host: str) -> None:
    with _lock:
        wait = _last.get(host, 0) + HOST_DELAY - time.monotonic()
        _last[host] = max(time.monotonic(), _last.get(host, 0) + HOST_DELAY)
    if wait > 0:
        time.sleep(wait)


def _client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "ar,en;q=0.8"},
                        timeout=TIMEOUT, follow_redirects=True)


def allowed(url: str) -> bool:
    """robots.txt: نحترم منع الزواحف. إن تعذّرت قراءته نعتبره مسموحًا (السلوك المعتاد)."""
    p = urlparse(url)
    key = f"{p.scheme}://{p.netloc}"
    now = time.time()
    cached = _robots.get(key)
    if cached is None or now - cached[0] > 6 * 3600:
        rp: RobotFileParser | None = RobotFileParser()
        try:
            with _client() as c:
                r = c.get(f"{key}/robots.txt")
            if r.status_code >= 400:
                rp = None
            else:
                rp.parse(r.text.splitlines())
        except httpx.HTTPError:
            rp = None
        _robots[key] = (now, rp)
        cached = _robots[key]
    rp = cached[1]
    return True if rp is None else rp.can_fetch(USER_AGENT, url)


def get(url: str, *, etag: str = "", last_modified: str = "", check_robots: bool = True) -> httpx.Response:
    if check_robots and not allowed(url):
        raise FetchError("ملف robots.txt في الموقع يمنع جلب هذه الصفحة", 403)
    _throttle(urlparse(url).netloc)
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with _client() as c:
            r = c.get(url, headers=headers)
    except httpx.TimeoutException:
        raise FetchError("انتهت مهلة الاتصال بالموقع") from None
    except httpx.HTTPError as e:
        raise FetchError(f"تعذّر الاتصال: {e.__class__.__name__}") from None
    if len(r.content) > MAX_BYTES:
        raise FetchError("الصفحة أكبر من المسموح")
    if r.status_code >= 400:
        raise FetchError(f"ردّ الموقع بخطأ {r.status_code}", r.status_code)
    return r


def parse_html(r: httpx.Response):
    """يحلل الصفحة بترميزها الصحيح: من ترويسة HTTP إن وُجد، وإلا من داخل الصفحة."""
    from lxml import html as lxml_html

    ctype = r.headers.get("content-type", "").lower()
    if "charset=" in ctype:
        try:
            return lxml_html.fromstring(r.text)
        except ValueError:  # نص فيه إعلان ترميز XML
            pass
    return lxml_html.fromstring(r.content)
