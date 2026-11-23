import pyotp

from tests.conftest import ADMIN, invite_user


def test_first_run_setup_creates_admin_once(make_client):
    c = make_client()
    assert c.get("/api/setup").json()["needs_setup"] is True
    r = c.post("/api/setup", json=ADMIN)
    assert r.status_code == 200
    assert "users.manage" in r.json()["access"]["effective"]
    assert c.get("/api/setup").json()["needs_setup"] is False
    assert make_client().post("/api/setup", json=ADMIN).status_code == 409


def test_short_password_rejected(make_client):
    r = make_client().post("/api/setup", json={**ADMIN, "password": "short"})
    assert r.status_code == 400 and "قصيرة" in r.json()["detail"]


def test_login_logout(admin, make_client):
    c = make_client()
    assert c.get("/api/me").status_code == 401
    r = c.post("/api/auth/login", json={"email": "GHAYTH@example.com ", "password": ADMIN["password"]})
    assert r.status_code == 200
    assert c.get("/api/me").json()["email"] == ADMIN["email"]
    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401


def test_case2_lockout_after_five_wrong_passwords(admin, make_client):
    """حالة الفحص 2: خمس محاولات خاطئة تقفل الحساب مؤقتًا ويُسجَّل الحدث."""
    c = make_client()
    for _ in range(5):
        assert c.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong-pass-xx"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 401 and "مقفل" in r.json()["detail"]
    actions = [a["action"] for a in admin.get("/api/admin/audit").json()]
    assert "login.lockout" in actions


def test_unknown_email_gives_same_message(admin, make_client):
    c = make_client()
    a = c.post("/api/auth/login", json={"email": "nobody@x.com", "password": "whatever-123"}).json()
    b = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": "whatever-123"}).json()
    assert a["detail"] == b["detail"]


def test_totp_two_step(admin, make_client):
    uri = admin.post("/api/me/totp/start").json()["otpauth_uri"]
    secret = pyotp.parse_uri(uri).secret
    assert admin.post("/api/me/totp/confirm", json={"code": "000000"}).status_code == 400
    assert admin.post("/api/me/totp/confirm", json={"code": pyotp.TOTP(secret).now()}).status_code == 200
    c = make_client()
    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 401 and "رمز" in r.json()["detail"]
    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"],
                                        "totp": pyotp.TOTP(secret).now()})
    assert r.status_code == 200


def test_invite_flow_and_single_use(admin, make_client):
    r = admin.post("/api/admin/users", json={"email": "sara@example.com", "roles": [{"key": "journalist"}]})
    token = r.json()["invite_token"]
    c = make_client()
    assert c.post("/api/invite/accept", json={"token": token, "password": "sara-password-1"}).status_code == 200
    assert make_client().post("/api/invite/accept", json={"token": token, "password": "other-password-1"}).status_code == 400


def test_csrf_header_required(admin):
    r = admin.post("/api/auth/logout", headers={"X-Marsad": "0"})
    assert r.status_code == 403


def test_deactivated_user_loses_session(admin, make_client):
    c, uid = invite_user(admin, make_client, "x@example.com", ["journalist"])
    assert c.get("/api/me").status_code == 200
    admin.put(f"/api/admin/users/{uid}/active", json={"active": False})
    assert c.get("/api/me").status_code == 401
