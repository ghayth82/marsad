"""الحضور: من يفتح الصفحة نفسها الآن (بطاقة ادّعاء، مسودة، قضية). نبضة كل 15 ثانية، ومن غاب 40 ثانية يختفي.

يعيش في ذاكرة الخادم (عملية واحدة على الجهاز والخادم)، فلا يكتب في قاعدة البيانات مع كل نبضة."""

from __future__ import annotations

import re
import threading
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from marsad.api.deps import current_user
from marsad.models import User

router = APIRouter(prefix="/api", tags=["presence"])
_LOCK = threading.Lock()
_SEEN: dict[str, dict[int, tuple[str, float, bool]]] = {}
TTL = 40
PATH = re.compile(r"^/(claims|story-builder|cases)/\d+")


class Beat(BaseModel):
    path: str
    editing: bool = False


@router.post("/presence")
def beat(body: Beat, user: User = Depends(current_user)):
    m = PATH.match(body.path)
    if not m:
        raise HTTPException(422, "مسار غير متابع")
    key, now = m.group(0), time.time()
    with _LOCK:
        room = _SEEN.setdefault(key, {})
        room[user.id] = (user.full_name or user.email, now, body.editing)
        for uid in [u for u, (_, t, _) in room.items() if now - t > TTL]:
            room.pop(uid, None)
        others = [{"user_id": u, "name": n, "editing": e} for u, (n, t, e) in room.items() if u != user.id]
    return {"others": others}


def reset() -> None:
    with _LOCK:
        _SEEN.clear()
