"""الحالات 4 و5 و6: كل شاشة بالأنماط الثلاثة، على عرض حاسوب وعرض هاتف — بلا تجاوز أفقي ولا خطأ في الصفحة ولا نص مكسور،
والنص المختلط (عربي وإنجليزي وأرقام) يبقى باتجاه صحيح، والنمط المختار يُحفظ."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("MARSAD_E2E_URL", "http://localhost:8000")
SHOTS = Path(os.environ.get("MARSAD_E2E_SHOTS", "e2e/screenshots"))
CHROME = os.environ.get("MARSAD_E2E_CHROME")
INSECURE = os.environ.get("MARSAD_E2E_INSECURE") == "1"
H = {"X-Marsad": "1"}
ADMIN = {"email": "ghayth@example.com", "password": "correct-horse-1", "full_name": "غيث"}
ROUTES = ["/", "/sources", "/live", "/stories", "/rumors", "/media-lab", "/audio-lab", "/entities", "/cases", "/story-builder",
          "/ratings", "/ratings/methodology", "/ratings/review", "/engines", "/reports", "/stats", "/tools/tips", "/tools/figures", "/tools/promises", "/tools/transcripts", "/tools/archive", "/tools/workflow", "/tools/corrections", "/admin/api", "/training", "/admin", "/admin/settings",
          "/admin/roles", "/help", "/me"]
MIXED = "أعلنت شركة Apple عن iPhone 17 بسعر 999 دولار (1,299 USD مع الضريبة) في 2026-11-24"


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME) if CHROME else p.chromium.launch()
        ctx = browser.new_context(ignore_https_errors=INSECURE)
        if ctx.request.get(f"{BASE}/api/setup").json()["needs_setup"]:
            assert ctx.request.post(f"{BASE}/api/setup", data=ADMIN, headers=H).ok
        else:
            assert ctx.request.post(f"{BASE}/api/auth/login", data=ADMIN, headers=H).ok
        cid = ctx.request.post(f"{BASE}/api/claims", data={"text": MIXED}, headers=H).json()["id"]
        case = ctx.request.post(f"{BASE}/api/cases", data={"title": "قضية فحص الشاشات"}, headers=H).json()["id"]
        routes = ROUTES + [f"/claims/{cid}", f"/cases/{case}", f"/cases/{case}/docs", f"/cases/{case}/money"]
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for pattern in ("c", "b", "a"):
            assert ctx.request.patch(f"{BASE}/api/me/preferences", data={"pattern": pattern}, headers=H).ok
            for width, height, label in ((1440, 900, "desktop"), (390, 844, "mobile")):
                page.set_viewport_size({"width": width, "height": height})
                for r in routes:
                    errors.clear()
                    page.goto(f"{BASE}{r}")
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(150)
                    info = page.evaluate("""() => ({
                        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
                        pattern: document.documentElement.dataset.pattern || document.body.dataset.pattern || '',
                        bad: [...document.querySelectorAll('main *')].filter(e => e.children.length === 0 &&
                              /\\b(undefined|NaN|null)\\b|\\[object Object\\]/.test(e.textContent)).map(e => e.textContent.slice(0, 60)).slice(0, 3),
                        clipped: [...document.querySelectorAll('main h1, main h2, main .btn, main .pill')].filter(e =>
                              e.scrollWidth > e.clientWidth + 2 && getComputedStyle(e).overflow !== 'visible').map(e => e.textContent.slice(0, 40)).slice(0, 3),
                    })""")
                    if info["overflow"] > 2:
                        problems.append(f"{pattern}/{label} {r}: تجاوز أفقي {info['overflow']}px")
                    if info["bad"]:
                        problems.append(f"{pattern}/{label} {r}: نص مكسور {info['bad']}")
                    if info["clipped"]:
                        problems.append(f"{pattern}/{label} {r}: نص مقطوع {info['clipped']}")
                    if errors:
                        problems.append(f"{pattern}/{label} {r}: خطأ في الصفحة {errors[:2]}")
                page.screenshot(path=SHOTS / f"95-{pattern}-{label}-claim.png", full_page=True)
        # النمط يُحفظ ويتبع المستخدم بعد إعادة الدخول
        assert ctx.request.get(f"{BASE}/api/me").json()["preferences"]["pattern"] == "a"
        # النص المختلط: الاتجاه العام من اليمين، والأرقام والكلمات الإنجليزية في مكانها
        page.set_viewport_size({"width": 1440, "height": 900})
        page.goto(f"{BASE}/claims/{cid}")
        h = page.get_by_role("heading", name=f"«{MIXED}»")
        expect(h).to_be_visible()
        assert h.evaluate("e => getComputedStyle(e).direction") == "rtl"
        assert h.inner_text() == f"«{MIXED}»"
        ctx.request.patch(f"{BASE}/api/me/preferences", data={"pattern": "c"}, headers=H)
        browser.close()
    if problems:
        print("\n".join(problems))
        return 1
    print(f"E2E الشاشات: {len(routes)} شاشة × 3 أنماط × عرضان — لا مشكلات")
    return 0


if __name__ == "__main__":
    sys.exit(main())
