import os
import base64
from datetime import timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .auth import current_user, get_db, hash_password, verify_password
from .db import User, Lead, Activity, Sale, AuditLog, utcnow

router = APIRouter()

ADMIN_EMAIL = os.getenv("REVIFY_USER_EMAIL", "").strip().lower()
VALID_STATUSES = {"pending","owner_absent","closed","follow_up","won","lost"}

def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin" and user.email.lower() != ADMIN_EMAIL:
        raise HTTPException(status_code=403, detail="Acceso de administrador requerido")
    return user

class AdminUserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    temporary_password: str = Field(min_length=10, max_length=200)

class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=10, max_length=200)

class ActivePatch(BaseModel):
    is_active: bool

class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)

def _encode_cursor(x: Lead) -> str:
    raw = f"{int(x.updated_at.timestamp()*1000000)}:{x.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _decode_cursor(cursor: str):
    try:
        raw = base64.urlsafe_b64decode((cursor + "=" * (-len(cursor) % 4)).encode()).decode()
        micros, lead_id = raw.split(":", 1)
        dt = utcnow().fromtimestamp(int(micros) / 1_000_000, tz=timezone.utc)
        return dt, int(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Cursor no válido")

def _lead_out(x: Lead, rep_email: str = ""):
    return {
        "id": x.id,
        "name": x.name,
        "address": x.address or "",
        "postal_code": x.postal_code,
        "business_type": x.business_type,
        "business_subtype": x.business_subtype or "",
        "owner_name": x.owner_name or "",
        "phone": x.phone or "",
        "status": x.status,
        "next_action": x.next_action or "",
        "assigned_user_id": x.assigned_user_id,
        "rep_email": rep_email,
        "created_at": x.created_at.isoformat(),
        "updated_at": x.updated_at.isoformat(),
    }

@router.get("/api/admin/me")
def admin_me(admin: User = Depends(require_admin)):
    return {"id": admin.id, "email": admin.email, "role": "admin"}

@router.get("/api/admin/summary")
def admin_summary(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    user_count = db.scalar(select(func.count()).select_from(User).where(User.is_active == True)) or 0
    lead_count = db.scalar(select(func.count()).select_from(Lead)) or 0
    won_leads = db.scalar(select(func.count()).select_from(Lead).where(Lead.status == "won")) or 0
    visits_today = db.scalar(select(func.count()).select_from(Activity).where(Activity.activity_type == "visit", Activity.created_at >= today)) or 0
    demos_today = db.scalar(select(func.count()).select_from(Activity).where(Activity.activity_type == "demo", Activity.created_at >= today)) or 0
    sales_today = db.scalar(select(func.count()).select_from(Sale).where(Sale.created_at >= today)) or 0
    revenue_today = db.scalar(select(func.coalesce(func.sum(Sale.total), 0)).where(Sale.created_at >= today)) or 0
    sales_total = db.scalar(select(func.count()).select_from(Sale)) or 0
    revenue_total = db.scalar(select(func.coalesce(func.sum(Sale.total), 0))) or 0

    postal_rows = db.execute(
        select(Lead.postal_code, func.count(Lead.id))
        .group_by(Lead.postal_code)
        .order_by(func.count(Lead.id).desc())
        .limit(8)
    ).all()
    category_rows = db.execute(
        select(Lead.business_type, func.count(Lead.id))
        .group_by(Lead.business_type)
        .order_by(func.count(Lead.id).desc())
        .limit(8)
    ).all()

    return {
        "active_users": user_count,
        "leads": lead_count,
        "won_leads": won_leads,
        "conversion_pct": round((won_leads / lead_count * 100), 1) if lead_count else 0,
        "visits_today": visits_today,
        "demos_today": demos_today,
        "sales_today": sales_today,
        "revenue_today": float(revenue_today),
        "sales_total": sales_total,
        "revenue_total": float(revenue_total),
        "postal_codes": [{"postal_code": r[0], "leads": r[1]} for r in postal_rows],
        "categories": [{"category": r[0], "leads": r[1]} for r in category_rows],
    }

@router.get("/api/admin/reps")
def admin_reps(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = list(db.scalars(select(User).order_by(User.created_at.asc())).all())
    out = []
    for u in users:
        leads = db.scalar(select(func.count()).select_from(Lead).where(Lead.assigned_user_id == u.id)) or 0
        won = db.scalar(select(func.count()).select_from(Lead).where(Lead.assigned_user_id == u.id, Lead.status == "won")) or 0
        visits = db.scalar(select(func.count()).select_from(Activity).where(Activity.actor_user_id == u.id, Activity.activity_type == "visit")) or 0
        sales = db.scalar(select(func.count()).select_from(Sale).where(Sale.actor_user_id == u.id)) or 0
        revenue = db.scalar(select(func.coalesce(func.sum(Sale.total), 0)).where(Sale.actor_user_id == u.id)) or 0
        is_admin = u.role == "admin" or u.email.lower() == ADMIN_EMAIL
        out.append({
            "id": u.id,
            "email": u.email,
            "role": "admin" if is_admin else u.role,
            "is_active": u.is_active,
            "leads": leads,
            "won": won,
            "visits": visits,
            "sales": sales,
            "revenue": float(revenue),
            "conversion_pct": round((won / leads * 100), 1) if leads else 0,
        })
    return {"items": out}

@router.post("/api/admin/users")
def create_commercial(data: AdminUserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email")
    user = User(
        email=email,
        password_hash=hash_password(data.temporary_password),
        role="commercial",
        is_active=True,
    )
    db.add(user)
    db.flush()
    db.add(AuditLog(
        actor_user_id=admin.id,
        lead_id=None,
        event_type="commercial_created",
        payload='{"commercial_user_id": %d}' % user.id,
    ))
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role, "is_active": user.is_active}

@router.post("/api/admin/users/{user_id}/reset-password")
def reset_commercial_password(
    user_id: int,
    data: AdminPasswordReset,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    target.password_hash = hash_password(data.new_password)
    db.add(AuditLog(
        actor_user_id=admin.id,
        lead_id=None,
        event_type="commercial_password_reset",
        payload='{"commercial_user_id": %d}' % target.id,
    ))
    db.commit()
    return {"ok": True}

@router.patch("/api/admin/users/{user_id}/active")
def set_commercial_active(
    user_id: int,
    data: ActivePatch,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.id == admin.id and not data.is_active:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propio usuario administrador")
    target.is_active = data.is_active
    db.add(AuditLog(
        actor_user_id=admin.id,
        lead_id=None,
        event_type="commercial_access_changed",
        payload='{"commercial_user_id": %d, "is_active": %s}' % (target.id, str(data.is_active).lower()),
    ))
    db.commit()
    return {"ok": True, "is_active": target.is_active}

@router.get("/api/admin/leads")
def admin_leads(
    search: str = "",
    postal_code: str = "",
    business_type: str = "",
    status: str = "",
    assigned_user_id: Optional[int] = None,
    cursor: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = select(Lead)
    if search:
        s = f"%{search.strip().lower()}%"
        q = q.where(or_(
            func.lower(Lead.name).like(s),
            func.lower(func.coalesce(Lead.address, "")).like(s),
            func.lower(Lead.postal_code).like(s),
            func.lower(Lead.business_type).like(s),
            func.lower(func.coalesce(Lead.business_subtype, "")).like(s),
            func.lower(func.coalesce(Lead.owner_name, "")).like(s),
        ))
    if postal_code:
        q = q.where(Lead.postal_code == postal_code.strip())
    if business_type:
        q = q.where(Lead.business_type == business_type)
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Estado no válido")
        q = q.where(Lead.status == status)
    if assigned_user_id:
        q = q.where(Lead.assigned_user_id == assigned_user_id)
    if cursor:
        dt, lead_id = _decode_cursor(cursor)
        q = q.where(or_(Lead.updated_at < dt, (Lead.updated_at == dt) & (Lead.id < lead_id)))

    rows = list(db.scalars(q.order_by(Lead.updated_at.desc(), Lead.id.desc()).limit(limit + 1)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    user_ids = {x.assigned_user_id for x in rows}
    emails = {}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all():
            emails[u.id] = u.email

    return {
        "items": [_lead_out(x, emails.get(x.assigned_user_id, "")) for x in rows],
        "next_cursor": _encode_cursor(rows[-1]) if has_more and rows else None,
    }

@router.post("/api/account/password")
def change_own_password(
    data: PasswordChange,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
    user.password_hash = hash_password(data.new_password)
    db.add(AuditLog(
        actor_user_id=user.id,
        lead_id=None,
        event_type="password_changed",
        payload="{}",
    ))
    db.commit()
    return {"ok": True}
