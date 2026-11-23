from datetime import datetime, timedelta, timezone

from tests.conftest import invite_user


def _me(c):
    return c.get("/api/me").json()["access"]


def test_case3_editor_cannot_open_settings(admin, make_client):
    """حالة الفحص 3: محرّر يحاول فتح الإعدادات فيُمنع برسالة واضحة."""
    c, _ = invite_user(admin, make_client, "ed@example.com", ["editor"])
    r = c.get("/api/admin/users")
    assert r.status_code == 403 and "صلاحية" in r.json()["detail"]
    assert c.get("/api/admin/storage").status_code == 403


def test_case44_user_with_two_roles_gets_union(admin, make_client):
    """حالة الفحص 44: مستخدم بدوري صحفي وباحث يرى صلاحيات الدورين، والإسناد مسجّل."""
    c, uid = invite_user(admin, make_client, "two@example.com", ["journalist", "researcher"])
    access = _me(c)
    assert {r["key"] for r in access["roles"]} == {"journalist", "researcher"}
    assert "claims.create" in access["effective"]  # من الصحفي
    assert "data.export" in access["effective"]  # من الباحث
    actions = [(a["action"], a["target_id"]) for a in admin.get("/api/admin/audit").json()]
    assert ("user.role.assign", str(uid)) in actions


def test_set_roles_replaces_all(admin, make_client):
    c, uid = invite_user(admin, make_client, "r@example.com", ["trainee"])
    r = admin.put(f"/api/admin/users/{uid}/roles", json={"roles": [{"key": "journalist"}, {"key": "editor"}]})
    assert r.status_code == 200
    assert {x["key"] for x in _me(c)["roles"]} == {"journalist", "editor"}


def test_case45_individual_grant_and_deny(admin, make_client):
    """حالة الفحص 45: سحب التصدير من باحث ومنحه لصحفي دون تغيير الأدوار."""
    res, rid = invite_user(admin, make_client, "res@example.com", ["researcher"])
    jou, jid = invite_user(admin, make_client, "jou@example.com", ["journalist"])
    admin.put(f"/api/admin/users/{rid}/permissions", json={"permission": "data.export", "effect": "deny"})
    admin.put(f"/api/admin/users/{jid}/permissions", json={"permission": "data.export", "effect": "grant"})
    assert "data.export" not in _me(res)["effective"]
    assert "data.export" in _me(jou)["effective"]
    assert [r["key"] for r in _me(res)["roles"]] == ["researcher"]
    # إزالة الاستثناء تعيد ما تقرره الأدوار
    admin.put(f"/api/admin/users/{rid}/permissions", json={"permission": "data.export", "effect": None})
    assert "data.export" in _me(res)["effective"]


def test_case47_temporary_role_expires(admin, make_client):
    """حالة الفحص 47: دور مؤقت يختفي تلقائيًا بعد انتهائه."""
    c, uid = invite_user(admin, make_client, "t@example.com", ["researcher"])
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    admin.put(f"/api/admin/users/{uid}/roles", json={"roles": [
        {"key": "researcher"}, {"key": "trainee", "expires_at": future}]})
    assert "training.participate" in _me(c)["effective"]
    admin.put(f"/api/admin/users/{uid}/roles", json={"roles": [
        {"key": "researcher"}, {"key": "trainee", "expires_at": past}]})
    access = _me(c)
    assert "training.participate" not in access["effective"]
    assert any(r["key"] == "trainee" and r["active"] is False for r in access["roles"])


def test_custom_role(admin, make_client):
    r = admin.post("/api/admin/roles", json={"key": "image_checker", "name_ar": "مدقق صور",
                                             "permissions": ["labs.use", "monitor.view"]})
    assert r.status_code == 200
    c, _ = invite_user(admin, make_client, "img@example.com", ["image_checker"])
    assert set(_me(c)["effective"]) == {"labs.use", "monitor.view"}
    assert admin.post("/api/admin/roles", json={"key": "bad", "name_ar": "x",
                                                "permissions": ["nope"]}).status_code == 409


def test_cannot_remove_last_admin(admin):
    me = admin.get("/api/me").json()
    uid = me["id"]
    r = admin.put(f"/api/admin/users/{uid}/roles", json={"roles": [{"key": "journalist"}]})
    assert r.status_code == 409 and "مدير" in r.json()["detail"]
    r = admin.put(f"/api/admin/users/{uid}/permissions", json={"permission": "users.manage", "effect": "deny"})
    assert r.status_code == 409
    r = admin.put(f"/api/admin/users/{uid}/active", json={"active": False})
    assert r.status_code == 409
    assert "users.manage" in _me(admin)["effective"]  # لم يتغير شيء


def test_second_admin_allows_demotion(admin, make_client):
    other, oid = invite_user(admin, make_client, "boss2@example.com", ["admin"])
    uid = admin.get("/api/me").json()["id"]
    assert admin.put(f"/api/admin/users/{uid}/roles", json={"roles": [{"key": "journalist"}]}).status_code == 200
    assert "users.manage" not in _me(admin)["effective"]


def test_admin_role_permissions_fixed_and_builtin_not_deletable(admin):
    assert admin.put("/api/admin/roles/admin/permissions", json={"permissions": []}).status_code == 409
    assert admin.delete("/api/admin/roles/editor").status_code == 409


def test_deleting_custom_role_that_holds_only_admin_power_is_guarded(admin, make_client):
    admin.post("/api/admin/roles", json={"key": "superuser", "name_ar": "مشرف", "permissions": ["users.manage"]})
    other, oid = invite_user(admin, make_client, "su@example.com", ["superuser"])
    uid = admin.get("/api/me").json()["id"]
    admin.put(f"/api/admin/users/{uid}/roles", json={"roles": [{"key": "journalist"}]})  # المدير الثاني موجود
    r = other.delete("/api/admin/roles/superuser")
    assert r.status_code == 409  # حذفه يترك البرنامج دون مدير


def test_case46_four_eyes(admin, make_client):
    """حالة الفحص 46: من كتب العمل لا يعتمده بنفسه حين تُفعَّل القاعدة."""
    from marsad.db import get_db
    from marsad.models import User
    from marsad.rbac.service import PermissionError_, check_can_approve

    c, uid = invite_user(admin, make_client, "ed2@example.com", ["journalist", "editor"])
    db = next(get_db())
    check_can_approve(db, db.get(User, uid), uid, "verdicts.approve")  # القاعدة معطّلة افتراضيًا
    db.close()
    assert admin.put("/api/admin/settings/four-eyes", json={"enabled": True}).status_code == 200
    db = next(get_db())
    user = db.get(User, uid)
    try:
        check_can_approve(db, user, uid, "verdicts.approve")
        raise AssertionError("كان يجب الرفض")
    except PermissionError_ as e:
        assert "العينان الأربع" in str(e)
    check_can_approve(db, user, uid + 999, "verdicts.approve")  # عمل غيره مسموح
    db.close()
