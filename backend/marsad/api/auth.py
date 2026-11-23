from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from marsad import preferences as prefs
from marsad.api.deps import SESSION_COOKIE, client_ip, current_user
from marsad.auth import service as auth
from marsad.config import get_settings
from marsad.db import get_db
from marsad.models import Role, User
from marsad.rbac import service as rbac
from marsad.rbac.permissions import PERMISSIONS

router = APIRouter(prefix="/api", tags=["auth"])


def _set_cookie(resp: Response, token: str) -> None:
    s = get_settings()
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", secure=s.cookie_secure,
                    max_age=s.session_hours * 3600, path="/")


def me_payload(db: Session, user: User) -> dict:
    return {
        "id": user.id, "email": user.email, "full_name": user.full_name,
        "totp_enabled": user.totp_enabled,
        "access": rbac.explain(user),
        "preferences": prefs.effective_preferences(db, user),
        "permission_labels": {k: v["ar"] for k, v in PERMISSIONS.items()},
    }


# ---------- أول تشغيل ----------

class SetupIn(BaseModel):
    email: str
    full_name: str = ""
    password: str


@router.get("/setup")
def setup_status(db: Session = Depends(get_db)):
    return {"needs_setup": db.scalar(select(func.count(User.id))) == 0, "mode": get_settings().mode}


@router.post("/setup")
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)):
    if db.scalar(select(func.count(User.id))) > 0:
        raise HTTPException(409, "البرنامج مُعدّ مسبقًا")
    rbac.seed_builtin_roles(db)
    try:
        user = User(email=auth.normalize_email(body.email), full_name=body.full_name,
                    password_hash=auth.hash_password(body.password))
    except auth.AuthError as e:
        raise HTTPException(400, str(e)) from None
    db.add(user)
    db.flush()
    rbac.assign_role(db, None, user, db.scalar(select(Role).where(Role.key == "admin")))
    token = auth.create_session(db, user, client_ip(request), request.headers.get("user-agent", ""))
    db.commit()
    _set_cookie(response, token)
    return me_payload(db, user)


# ---------- الدخول والخروج ----------

class LoginIn(BaseModel):
    email: str
    password: str
    totp: str | None = None


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        user = auth.authenticate(db, body.email, body.password, body.totp, client_ip(request))
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from None
    token = auth.create_session(db, user, client_ip(request), request.headers.get("user-agent", ""))
    db.commit()
    _set_cookie(response, token)
    return me_payload(db, user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    auth.end_session(db, request.cookies.get(SESSION_COOKIE))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return me_payload(db, user)


class PasswordIn(BaseModel):
    old: str
    new: str


@router.post("/me/password")
def change_password(body: PasswordIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        auth.change_password(db, user, body.old, body.new)
    except auth.AuthError as e:
        raise HTTPException(400, str(e)) from None
    db.commit()
    return {"ok": True}


@router.post("/me/totp/start")
def totp_start(user: User = Depends(current_user), db: Session = Depends(get_db)):
    uri = auth.start_totp(user)
    db.commit()
    return {"otpauth_uri": uri}


class CodeIn(BaseModel):
    code: str


@router.post("/me/totp/confirm")
def totp_confirm(body: CodeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        auth.confirm_totp(db, user, body.code)
    except auth.AuthError as e:
        raise HTTPException(400, str(e)) from None
    db.commit()
    return {"ok": True}


class AcceptIn(BaseModel):
    token: str
    password: str


@router.post("/invite/accept")
def accept_invite(body: AcceptIn, request: Request, response: Response, db: Session = Depends(get_db)):
    try:
        user = auth.accept_invite(db, body.token, body.password)
    except auth.AuthError as e:
        raise HTTPException(400, str(e)) from None
    token = auth.create_session(db, user, client_ip(request), request.headers.get("user-agent", ""))
    db.commit()
    _set_cookie(response, token)
    return me_payload(db, user)


# ---------- تفضيلاتي ----------

@router.get("/me/preferences")
def get_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return prefs.effective_preferences(db, user)


@router.patch("/me/preferences")
def patch_prefs(changes: dict, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        out = prefs.update_preferences(db, user, changes)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    return out


@router.delete("/me/preferences")
def reset_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    out = prefs.reset_preferences(db, user)
    db.commit()
    return out
