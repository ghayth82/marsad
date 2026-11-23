from tests.conftest import invite_user


def test_case39_each_user_has_own_interface(admin, make_client):
    """حالة الفحص 39: مستخدمان بنمطين ولغتين مختلفتين، ولا يتأثر أحدهما بالآخر،
    والتفضيلات تتبع المستخدم إلى جهاز آخر (جلسة جديدة)."""
    a, _ = invite_user(admin, make_client, "a@example.com", ["journalist"], "pass-a-123456")
    b, _ = invite_user(admin, make_client, "b@example.com", ["journalist"], "pass-b-123456")
    assert a.patch("/api/me/preferences", json={"pattern": "a", "theme": "dark"}).status_code == 200
    assert b.patch("/api/me/preferences", json={"pattern": "b", "language": "en"}).status_code == 200
    pa, pb = a.get("/api/me/preferences").json(), b.get("/api/me/preferences").json()
    assert (pa["pattern"], pa["theme"], pa["language"]) == ("a", "dark", "ar")
    assert (pb["pattern"], pb["language"]) == ("b", "en")
    other_device = make_client()
    other_device.post("/api/auth/login", json={"email": "a@example.com", "password": "pass-a-123456"})
    assert other_device.get("/api/me/preferences").json()["pattern"] == "a"


def test_invalid_preferences_rejected(admin):
    assert admin.patch("/api/me/preferences", json={"pattern": "z"}).status_code == 422
    assert admin.patch("/api/me/preferences", json={"dashboard": ["nope"]}).status_code == 422
    assert admin.patch("/api/me/preferences", json={"unknown_key": 1}).status_code == 422


def test_role_template_then_user_override(admin, make_client):
    assert admin.put("/api/admin/roles/trainee/template",
                     json={"pattern": "b", "dashboard": ["training"]}).status_code == 200
    c, _ = invite_user(admin, make_client, "tr@example.com", ["trainee"])
    p = c.get("/api/me/preferences").json()
    assert p["pattern"] == "b" and p["dashboard"] == ["training"]
    c.patch("/api/me/preferences", json={"pattern": "a"})
    assert c.get("/api/me/preferences").json()["pattern"] == "a"
    assert c.delete("/api/me/preferences").json()["pattern"] == "b"  # الرجوع لقالب الدور


def test_view_as_role_only_for_held_roles(admin, make_client):
    c, uid = invite_user(admin, make_client, "va@example.com", ["journalist", "researcher"])
    c.patch("/api/me/preferences", json={"view_as_role": "researcher"})
    assert c.get("/api/me/preferences").json()["view_as_role"] == "researcher"
    admin.put(f"/api/admin/users/{uid}/roles", json={"roles": [{"key": "journalist"}]})
    assert c.get("/api/me/preferences").json()["view_as_role"] is None


def test_storage_api_admin_only(admin, make_client, tmp_path):
    j, _ = invite_user(admin, make_client, "j@example.com", ["journalist"])
    assert j.get("/api/admin/storage").status_code == 403
    st = admin.get("/api/admin/storage").json()
    assert st["data_dir"] == "./data" and st["restart_required"] is False
    r = admin.post("/api/admin/storage", json={"data_dir": str(tmp_path / "D" / "Marsad")})
    assert r.status_code == 200 and r.json()["restart_required"] is True
    assert admin.post("/api/admin/storage", json={"data_dir": "./data"}).status_code == 422
    assert admin.delete("/api/admin/storage/pending").json()["restart_required"] is False
