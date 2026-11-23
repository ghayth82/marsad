"""الربط بمحركات «صوتي» للتفريغ وتمييز المتحدثين.

على الجهاز: تُستدعى مباشرة عبر غلاف سطح المكتب حين تُضمَّن محركات «صوتي».
على الخادم: خدمة صغيرة مستقلة؛ عنوانها في MARSAD_SAWTI_URL (POST /transcribe، ملف صوتي → نص بتوقيت كل جملة).
إن لم تتوفر، يُقال ذلك بوضوح ولا يُخترع تفريغ.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx


def transcribe(path: Path) -> dict:
    url = os.environ.get("MARSAD_SAWTI_URL")
    if not url:
        return {"available": False, "summary": "التفريغ يتم بمحركات «صوتي»، وهي غير موصولة بعد في هذا التثبيت", "segments": []}
    try:
        with open(path, "rb") as f:
            r = httpx.post(f"{url.rstrip('/')}/transcribe", files={"file": (path.name, f)}, data={"language": "ar"},
                           timeout=httpx.Timeout(900.0, connect=10.0))
        r.raise_for_status()
        d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"available": False, "summary": f"تعذّر الاتصال بمحركات «صوتي»: {e.__class__.__name__}", "segments": []}
    segs = [{"start": s.get("start"), "end": s.get("end"), "speaker": s.get("speaker", ""), "text": s.get("text", "")}
            for s in d.get("segments", [])]
    return {"available": True, "summary": f"تفريغ {len(segs)} جملة بتوقيتاتها" + (f" و{len({s['speaker'] for s in segs if s['speaker']})} متحدث" if any(s["speaker"] for s in segs) else ""),
            "segments": segs, "text": " ".join(s["text"] for s in segs)}
