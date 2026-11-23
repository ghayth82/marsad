from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from marsad.auth.service import user_from_session
from marsad.db import get_db
from marsad.models import User
from marsad.rbac.service import effective_permissions

SESSION_COOKIE = "marsad_session"


def client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_session(db, request.cookies.get(SESSION_COOKIE))
    if user is None:
        raise HTTPException(401, "سجّل الدخول أولًا")
    return user


def require(*permissions: str):
    """يتطلب كل الصلاحيات المذكورة."""

    def dep(user: User = Depends(current_user)) -> User:
        perms = effective_permissions(user)
        missing = [p for p in permissions if p not in perms]
        if missing:
            raise HTTPException(403, "لا تملك صلاحية لهذه الصفحة. اطلبها من المدير.")
        return user

    return dep
