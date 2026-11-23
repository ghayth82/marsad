"""حاسبة الشمس والظل: موقع الشمس لمكان ووقت، واتجاه الظل وطوله، لمقارنته بما في الصورة.
(خوارزمية NOAA المبسطة؛ دقتها أقل من درجة، وهي كافية لمقارنة الظلال.)"""

from __future__ import annotations

import math
from datetime import datetime, timezone


def sun_position(lat: float, lon: float, when: datetime) -> dict:
    when = when.astimezone(timezone.utc)
    jd = when.timestamp() / 86400.0 + 2440587.5
    n = jd - 2451545.0
    L = (280.460 + 0.9856474 * n) % 360
    g = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra = math.atan2(math.cos(eps) * math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps) * math.sin(lam))
    gmst = (18.697374558 + 24.06570982441908 * n) % 24
    ha = math.radians((gmst * 15 + lon) % 360) - ra
    la = math.radians(lat)
    el = math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha))
    az = math.atan2(-math.sin(ha), math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(ha))
    az_deg = (math.degrees(az) + 360) % 360
    el_deg = math.degrees(el)
    shadow = None if el_deg <= 0 else round(1 / math.tan(el), 2)
    return {"elevation": round(el_deg, 2), "azimuth": round(az_deg, 2),
            "shadow_azimuth": round((az_deg + 180) % 360, 2), "shadow_per_meter": shadow,
            "daylight": el_deg > 0}


def check_shadow(lat: float, lon: float, when: datetime, shadow_azimuth: float | None = None,
                 shadow_ratio: float | None = None) -> dict:
    """يقارن ظلًا مقيسًا من الصورة (اتجاهه، ونسبة طوله لطول الجسم) بالمتوقع في الوقت المدّعى."""
    s = sun_position(lat, lon, when)
    out = {"sun": s, "notes": []}
    if not s["daylight"]:
        out["notes"].append("الشمس تحت الأفق في هذا الوقت: صورة بظلال شمسية لا تتفق مع الوقت المدّعى")
        out["consistent"] = shadow_azimuth is None and shadow_ratio is None
        return out
    ok = True
    if shadow_azimuth is not None:
        diff = abs((shadow_azimuth - s["shadow_azimuth"] + 180) % 360 - 180)
        out["azimuth_diff"] = round(diff, 1)
        if diff > 25:
            ok = False
            out["notes"].append(f"اتجاه الظل يختلف {diff:.0f}° عن المتوقع")
    if shadow_ratio is not None and s["shadow_per_meter"]:
        rel = abs(shadow_ratio - s["shadow_per_meter"]) / s["shadow_per_meter"]
        out["ratio_diff"] = round(rel, 2)
        if rel > 0.35:
            ok = False
            out["notes"].append(f"طول الظل يختلف {rel * 100:.0f}٪ عن المتوقع")
    out["consistent"] = ok
    return out
