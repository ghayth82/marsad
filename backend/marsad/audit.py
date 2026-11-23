"""سجل التدقيق: كل عملية حساسة تُسجَّل هنا."""

from __future__ import annotations

from sqlalchemy.orm import Session

from marsad.models import AuditLog


def record(db: Session, actor, action: str, target_type: str = "", target_id: str = "",
           before: dict | None = None, after: dict | None = None, ip: str = "") -> None:
    db.add(AuditLog(actor_id=getattr(actor, "id", None), action=action, target_type=target_type,
                    target_id=str(target_id), before=before, after=after, ip=ip))
