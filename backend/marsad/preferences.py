"""تفضيلات المستخدم: الافتراضي ← قالب أعلى أدواره ← ما اختاره هو.

تُحفظ في قاعدة البيانات، فتتبع المستخدم إلى أي جهاز.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from marsad.audit import record
from marsad.models import RoleTemplate, User, UserPreference
from marsad.rbac.service import active_roles

DASHBOARD_CARDS = ["rising_stories", "new_rumors", "alerts", "sources_status", "daily_brief",
                   "my_cases", "pending_approvals", "engine_costs", "training", "my_tasks"]


class AlertPrefs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: list[Literal["telegram", "email", "in_app"]] = ["in_app"]
    urgent_only: bool = False
    quiet_hours: tuple[int, int] | None = None  # (من، إلى) بالساعة


class Appearance(BaseModel):
    """مظهر الواجهة لكل مستخدم: الخط والقراءة والألوان والكثافة."""
    model_config = ConfigDict(extra="forbid")
    font: Literal["noto", "naskh", "plex", "readex"] = "noto"
    leading: Literal["normal", "comfy", "wide"] = "comfy"
    read_scale: float = Field(1.0, ge=0.8, le=1.8)  # حجم نص الخبر وحده في القارئ
    read_width: Literal["narrow", "medium", "full"] = "medium"
    accent: Literal["teal", "blue", "indigo", "purple", "graphite"] = "teal"
    contrast: bool = False
    density: Literal["comfortable", "compact"] = "comfortable"
    hints: bool = True  # تلميحات الواجهة: تُخفى وتُظهر متى شاء المستخدم
    mode: Literal["full", "simple"] = "full"  # العرض المبسّط يخفي الخيارات المتقدمة


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pattern: Literal["a", "b", "c"] = "c"  # أ: غرفة الأخبار الليلية، ب: تحريري فاتح، ج: مساحة التحقيق
    theme: Literal["light", "dark", "system"] = "system"
    language: Literal["ar", "en"] = "ar"
    font_scale: float = Field(1.0, ge=0.8, le=1.6)
    appearance: Appearance = Field(default_factory=Appearance)
    tour_done: bool = False  # الجولة التعريفية عُرضت أو تُخطّيت
    dashboard: list[str] = Field(default_factory=lambda: ["my_tasks", "rising_stories", "new_rumors", "alerts",
                                                          "sources_status", "daily_brief"])
    view_as_role: str | None = None  # «عرض الواجهة كـ» دور واحد لمن يحمل أكثر من دور
    follows: dict[str, list[str]] = Field(default_factory=lambda: {"sources": [], "topics": [], "entities": []})
    saved_filters: list[dict] = Field(default_factory=list)
    engines: dict[str, str] = Field(default_factory=dict)  # المهمة ← المحرك المفضّل
    alerts: AlertPrefs = Field(default_factory=AlertPrefs)


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def validate(data: dict) -> dict:
    prefs = Preferences.model_validate(data)
    unknown = [c for c in prefs.dashboard if c not in DASHBOARD_CARDS]
    if unknown:
        raise ValueError(f"بطاقات غير معروفة: {', '.join(unknown)}")
    return prefs.model_dump(mode="json")


def role_template(db: Session, user: User) -> dict:
    for role in active_roles(user):
        tpl = db.get(RoleTemplate, role.id)
        if tpl and tpl.data:
            return tpl.data
    return {}


def effective_preferences(db: Session, user: User) -> dict:
    base = Preferences().model_dump(mode="json")
    own = db.get(UserPreference, user.id)
    merged = _merge(_merge(base, role_template(db, user)), own.data if own else {})
    if merged.get("view_as_role") and merged["view_as_role"] not in {r.key for r in active_roles(user)}:
        merged["view_as_role"] = None  # الدور سُحب أو انتهى
    return validate(merged)


def update_preferences(db: Session, user: User, changes: dict) -> dict:
    own = db.get(UserPreference, user.id)
    current = own.data if own else {}
    candidate = _merge(current, changes)
    validate(_merge(Preferences().model_dump(mode="json"), candidate))  # يرفض القيم الخاطئة
    if own is None:
        db.add(UserPreference(user_id=user.id, data=candidate))
    else:
        own.data = candidate
    db.flush()
    return effective_preferences(db, user)


def reset_preferences(db: Session, user: User) -> dict:
    own = db.get(UserPreference, user.id)
    if own:
        db.delete(own)
        db.flush()
    return effective_preferences(db, user)


def set_role_template(db: Session, actor: User, role_id: int, data: dict) -> dict:
    validate(_merge(Preferences().model_dump(mode="json"), data))
    tpl = db.get(RoleTemplate, role_id)
    before = tpl.data if tpl else None
    if tpl is None:
        db.add(RoleTemplate(role_id=role_id, data=data))
    else:
        tpl.data = data
    record(db, actor, "role.template", "role", str(role_id), before, data)
    db.flush()
    return data
