import os
import base64
import json
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from datetime import datetime, timedelta, timezone, time
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from .auth import current_user, get_db, hash_password, verify_password
from .db import User, Lead, Activity, Sale, AuditLog, InventoryMovement, utcnow

router = APIRouter()

ADMIN_EMAIL = os.getenv("REVIFY_USER_EMAIL", "").strip().lower()
VALID_STATUSES = {"pending","owner_absent","closed","follow_up","won","lost"}
STATUS_LABELS = {
    "pending": "Pendiente",
    "owner_absent": "No está el dueño",
    "closed": "Local cerrado",
    "follow_up": "Seguimiento",
    "won": "Vendido",
    "lost": "No interesado",
}

VISIT_ACTIVITY_TYPES = {"visit","demo","follow_up","owner_absent","closed","no_interest"}

POSTAL_ZONE_MAP = {
    "08001": "el Raval",
    "08002": "el Barri Gòtic",
    "08003": "la Barceloneta · Sant Pere, Santa Caterina i la Ribera",
    "08004": "el Poble-sec · la Font de la Guatlla",
    "08005": "Diagonal Mar i el Front Marítim del Poblenou · el Parc i la Llacuna del Poblenou · el Poblenou · la Vila Olímpica del Poblenou",
    "08006": "el Putxet i el Farró · la Vila de Gràcia · Sant Gervasi-Galvany",
    "08007": "l'Antiga Esquerra de l'Eixample · la Dreta de l'Eixample",
    "08008": "l'Antiga Esquerra de l'Eixample · la Dreta de l'Eixample",
    "08009": "la Dreta de l'Eixample",
    "08010": "la Dreta de l'Eixample",
    "08011": "l'Antiga Esquerra de l'Eixample · Sant Antoni",
    "08012": "la Vila de Gràcia",
    "08013": "el Fort Pienc · la Dreta de l'Eixample · la Sagrada Família",
    "08014": "Hostafrancs · la Bordeta · les Corts · Sants",
    "08015": "la Nova Esquerra de l'Eixample · Sant Antoni",
    "08016": "la Prosperitat · Porta · Vilapicina i la Torre Llobeta",
    "08017": "les Tres Torres · Sant Gervasi-Galvany · Sant Gervasi-la Bonanova · Sarrià · Vallvidrera, el Tibidabo i les Planes",
    "08018": "el Clot · el Fort Pienc · el Parc i la Llacuna del Poblenou · el Poblenou · Provençals del Poblenou · Sant Martí de Provençals",
    "08019": "Diagonal Mar i el Front Marítim del Poblenou · el Besòs i el Maresme · Provençals del Poblenou",
    "08020": "la Verneda i la Pau · Provençals del Poblenou · Sant Martí de Provençals",
    "08021": "Sant Gervasi-Galvany",
    "08022": "el Putxet i el Farró · Sant Gervasi-la Bonanova",
    "08023": "el Coll · el Putxet i el Farró · la Salut · Vallcarca i els Penitents",
    "08024": "Can Baró · el Baix Guinardó · el Camp d'en Grassot i Gràcia Nova · la Salut · la Vila de Gràcia",
    "08025": "el Baix Guinardó · el Camp d'en Grassot i Gràcia Nova · la Sagrada Família",
    "08026": "el Camp de l'Arpa del Clot · el Clot",
    "08027": "el Congrés i els Indians · la Sagrera · Navas",
    "08028": "la Maternitat i Sant Ramon · les Corts · Sants · Sants-Badal",
    "08029": "la Nova Esquerra de l'Eixample · les Corts",
    "08030": "Baró de Viver · el Bon Pastor · Sant Andreu",
    "08031": "Can Peguera · el Turó de la Peira · Horta · Vilapicina i la Torre Llobeta",
    "08032": "Can Baró · el Carmel · el Guinardó · Horta · la Clota · la Font d'en Fargues · la Teixonera",
    "08033": "Ciutat Meridiana · la Trinitat Nova · la Trinitat Vella · les Roquetes · Torre Baró · Vallbona",
    "08034": "Pedralbes · Sarrià",
    "08035": "el Coll · Horta · la Clota · la Teixonera · la Vall d'Hebron · Montbau · Sant Genís dels Agudells · Sant Gervasi-la Bonanova · Vallcarca i els Penitents · Vallvidrera, el Tibidabo i les Planes",
    "08036": "l'Antiga Esquerra de l'Eixample",
    "08037": "el Camp d'en Grassot i Gràcia Nova · la Dreta de l'Eixample",
    "08038": "el Poble-sec · la Marina de Port · la Marina del Prat Vermell",
    "08039": "Port de Barcelona · zona litoral/portuària",
    "08040": "la Marina del Prat Vermell",
    "08041": "el Camp de l'Arpa del Clot · el Guinardó · Navas",
    "08042": "Can Peguera · Canyelles · la Guineueta · la Trinitat Nova · les Roquetes · Verdun",
    "08070": "Correspondència oficial Correos/Telegràfs — codi especial",
    "08071": "Organismes oficials — codi especial",
    "08075": "Ciutat de la Justícia / Gran Via 111 — codi especial",
    "08080": "Apartats particulars i llista — codi especial",
    "08172": "Sant Cugat del Vallès — zona postal 08172",
    "08173": "Sant Cugat del Vallès — zona postal 08173",
    "08174": "Sant Cugat del Vallès — zona postal 08174",
    "08190": "Sant Cugat del Vallès — nucli urbà",
    "08195": "Mira-sol · Sant Cugat del Vallès",
    "08196": "Les Planes · Sant Cugat del Vallès",
    "08197": "Valldoreix · Sant Cugat del Vallès",
    "08198": "La Floresta · Vallpineda · Sant Cugat del Vallès",
    "08191": "Rubí",
}

POSTAL_SPECIAL_CODES = {"08070","08071","08075","08080"}
BARCELONA_TERRITORIAL_CODES = {f"080{i:02d}" for i in range(1,43)}
SANT_CUGAT_TERRITORIAL_CODES = {"08172","08173","08174","08190","08195","08196","08197","08198"}
RUBI_TERRITORIAL_CODES = {"08191"}
COVERAGE_POSTAL_CODES = BARCELONA_TERRITORIAL_CODES | SANT_CUGAT_TERRITORIAL_CODES | RUBI_TERRITORIAL_CODES

def postal_municipality(postal_code: str):
    cp=(postal_code or "").strip()
    if cp in BARCELONA_TERRITORIAL_CODES or cp in {"08070","08071","08075","08080"}:
        return "Barcelona"
    if cp in SANT_CUGAT_TERRITORIAL_CODES:
        return "Sant Cugat del Vallès"
    if cp in RUBI_TERRITORIAL_CODES:
        return "Rubí"
    return ""

def postal_zone(postal_code: str):
    cp=(postal_code or "").strip()
    label=POSTAL_ZONE_MAP.get(cp)
    municipality=postal_municipality(cp)
    if not label:
        return {
            "postal_code":cp,
            "municipality":municipality or "Fuera del directorio",
            "zone_label":"Fuera del directorio Barcelona · Sant Cugat · Rubí",
            "zone_short":"Fuera del área objetivo / sin zona",
            "is_special":False,
            "is_coverage_code":False,
        }
    parts=[p.strip() for p in label.split(" · ") if p.strip()]
    short=parts[0] if len(parts)==1 else (parts[0]+" · "+parts[1]+(f" +{len(parts)-2}" if len(parts)>2 else ""))
    return {
        "postal_code":cp,
        "municipality":municipality,
        "zone_label":label,
        "zone_short":short,
        "is_special":cp in POSTAL_SPECIAL_CODES,
        "is_coverage_code":cp in COVERAGE_POSTAL_CODES,
    }

def madrid_day_bounds():
    madrid=ZoneInfo("Europe/Madrid")
    now=datetime.now(madrid)
    start=datetime.combine(now.date(),time.min,tzinfo=madrid).astimezone(timezone.utc)
    end=datetime.combine(now.date(),time.max,tzinfo=madrid).astimezone(timezone.utc)
    return start,end

@lru_cache(maxsize=512)
def geocode_target_address(query: str):
    params=urlencode({
        "format":"jsonv2",
        "q":query,
        "addressdetails":1,
        "limit":8,
        "countrycodes":"es",
        "viewbox":"1.65,41.70,2.45,41.15",
        "bounded":1,
        "accept-language":"ca,es",
    })
    req=Request(
        "https://nominatim.openstreetmap.org/search?"+params,
        headers={"User-Agent":"RevifyCRM/1.0 (address resolver; admin use)"}
    )
    with urlopen(req,timeout=6) as response:
        data=json.loads(response.read().decode("utf-8"))
    out=[]
    seen=set()
    for item in data:
        addr=item.get("address") or {}
        cp=(addr.get("postcode") or "").strip()
        municipality=(
            addr.get("city") or addr.get("town") or addr.get("village") or
            addr.get("municipality") or addr.get("county") or ""
        )
        normalized=municipality.lower().replace("á","a").replace("é","e").replace("í","i").replace("ó","o").replace("ú","u").replace("à","a").replace("è","e").replace("ò","o").replace("ï","i").replace("ü","u")
        is_target=cp.startswith("08") or cp in POSTAL_ZONE_MAP or any(x in normalized for x in ["barcelona","sant cugat","rubi","rubí"])
        if not is_target:
            continue
        key=(item.get("display_name",""),cp)
        if key in seen:
            continue
        seen.add(key)
        zi=postal_zone(cp)
        neighborhood=addr.get("neighbourhood") or addr.get("suburb") or addr.get("quarter") or addr.get("city_district") or ""
        out.append({
            "display_name":item.get("display_name",""),
            "postal_code":cp,
            "municipality":zi["municipality"] or municipality,
            "neighborhood":neighborhood,
            "zone_label":zi["zone_label"],
            "zone_short":zi["zone_short"],
            "lat":item.get("lat"),
            "lon":item.get("lon"),
            "is_special":zi["is_special"],
        })
    return out

@lru_cache(maxsize=1)
def fetch_osm_postal_boundaries():
    query='''[out:json][timeout:35];
    (
      relation["boundary"="postal_code"]["postal_code"](41.26,1.82,41.66,2.32);
      relation["boundary"="administrative"]["postal_code"](41.26,1.82,41.66,2.32);
    );
    out body;
    >;
    out skel qt;'''
    req=Request(
        "https://overpass-api.de/api/interpreter",
        data=query.encode("utf-8"),
        headers={
            "User-Agent":"RevifyCRM/1.0 (postal boundary admin map)",
            "Content-Type":"application/x-www-form-urlencoded"
        },
        method="POST"
    )
    with urlopen(req,timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))

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

class InventoryMovementIn(BaseModel):
    quantity_delta: int = Field(ge=-100000, le=100000)
    notes: str = Field(default="", max_length=500)

def _encode_cursor(x: Lead) -> str:
    raw = f"{int(x.updated_at.timestamp()*1000000)}:{x.id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")

def _decode_cursor(cursor: str):
    try:
        raw = base64.urlsafe_b64decode((cursor + "=" * (-len(cursor) % 4)).encode()).decode()
        micros, lead_id = raw.split(":", 1)
        dt = datetime.fromtimestamp(int(micros) / 1_000_000, tz=timezone.utc)
        return dt, int(lead_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Cursor no válido")

def _period_start(days: int):
    if days <= 0:
        return None
    if days == 1:
        return madrid_day_bounds()[0]
    return utcnow() - timedelta(days=days)

def _merge_breakdown(base_rows, activity_rows, sale_rows, key_name):
    merged = {}
    for key, leads, won in base_rows:
        k = key or "Sin dato"
        merged[k] = {
            key_name: k,
            "leads": int(leads or 0),
            "won": int(won or 0),
            "visits": 0,
            "demos": 0,
            "followups": 0,
            "sales": 0,
            "units": 0,
            "revenue": 0.0,
        }
    for key, visits, demos, followups in activity_rows:
        k = key or "Sin dato"
        row = merged.setdefault(k, {key_name:k,"leads":0,"won":0,"visits":0,"demos":0,"followups":0,"sales":0,"units":0,"revenue":0.0})
        row["visits"] = int(visits or 0)
        row["demos"] = int(demos or 0)
        row["followups"] = int(followups or 0)
    for key, sales, units, revenue in sale_rows:
        k = key or "Sin dato"
        row = merged.setdefault(k, {key_name:k,"leads":0,"won":0,"visits":0,"demos":0,"followups":0,"sales":0,"units":0,"revenue":0.0})
        row["sales"] = int(sales or 0)
        row["units"] = int(units or 0)
        row["revenue"] = float(revenue or 0)
    rows = list(merged.values())
    for row in rows:
        row["conversion_pct"] = round((row["won"] / row["leads"] * 100), 1) if row["leads"] else 0
        row["sale_per_visit_pct"] = round((row["sales"] / row["visits"] * 100), 1) if row["visits"] else 0
        row["avg_ticket"] = round((row["revenue"] / row["sales"]), 2) if row["sales"] else 0
        row["revenue_per_lead"] = round((row["revenue"] / row["leads"]), 2) if row["leads"] else 0
    rows.sort(key=lambda r: (r["revenue"], r["leads"]), reverse=True)
    return rows

def _lead_filters(search="", postal_code="", business_type="", status="", assigned_user_id=None):
    conditions = []
    if search:
        s = f"%{search.strip().lower()}%"
        conditions.append(or_(
            func.lower(Lead.name).like(s),
            func.lower(func.coalesce(Lead.address, "")).like(s),
            func.lower(Lead.postal_code).like(s),
            func.lower(Lead.business_type).like(s),
            func.lower(func.coalesce(Lead.business_subtype, "")).like(s),
            func.lower(func.coalesce(Lead.owner_name, "")).like(s),
        ))
    if postal_code:
        conditions.append(Lead.postal_code == postal_code.strip())
    if business_type:
        conditions.append(Lead.business_type == business_type)
    if status:
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Estado no válido")
        conditions.append(Lead.status == status)
    if assigned_user_id:
        conditions.append(Lead.assigned_user_id == assigned_user_id)
    return conditions

@router.get("/api/admin/me")
def admin_me(admin: User = Depends(require_admin)):
    return {"id": admin.id, "email": admin.email, "role": "admin"}

@router.get("/api/admin/address-resolve")
def admin_address_resolve(
    q: str = Query(min_length=3, max_length=250),
    admin: User = Depends(require_admin),
):
    text_q=q.strip()
    try:
        items=geocode_target_address(text_q)
    except Exception as exc:
        raise HTTPException(status_code=502, detail="No se pudo consultar el geocodificador en este momento")
    return {"query":text_q,"items":items}

@router.get("/api/admin/postal-boundaries")
def admin_postal_boundaries(admin: User = Depends(require_admin)):
    try:
        raw=fetch_osm_postal_boundaries()
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudieron cargar los límites postales")
    return {
        "target_postal_codes":sorted(POSTAL_ZONE_MAP.keys()),
        "coverage_postal_codes":sorted(COVERAGE_POSTAL_CODES),
        "special_postal_codes":sorted(POSTAL_SPECIAL_CODES),
        "directory":[postal_zone(cp) for cp in sorted(POSTAL_ZONE_MAP.keys())],
        "osm":raw,
    }

@router.get("/api/address-resolve")
def address_resolve(
    q: str = Query(..., min_length=3, max_length=220),
    user: User = Depends(current_user),
):
    query=q.strip()
    try:
        items=geocode_target_address(query)
    except Exception:
        raise HTTPException(status_code=502, detail="No se pudo consultar el servicio de direcciones")
    return {"query":query,"items":items}


@router.post("/api/admin/inventory/movements")
def add_inventory_movement(
    data: InventoryMovementIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if data.quantity_delta == 0:
        raise HTTPException(status_code=400, detail="La cantidad no puede ser 0")
    movement=InventoryMovement(
        actor_user_id=admin.id,
        quantity_delta=data.quantity_delta,
        notes=data.notes.strip() or None,
    )
    db.add(movement)
    db.add(AuditLog(
        actor_user_id=admin.id,
        lead_id=None,
        event_type="inventory_adjusted",
        payload=json.dumps({"quantity_delta":data.quantity_delta,"notes":data.notes.strip()},ensure_ascii=False),
    ))
    db.commit()
    total_adjustments=int(db.scalar(select(func.coalesce(func.sum(InventoryMovement.quantity_delta),0))) or 0)
    sold_units=int(db.scalar(select(func.coalesce(func.sum(Sale.quantity),0))) or 0)
    return {
        "ok":True,
        "stock_available":total_adjustments-sold_units,
        "stock_movements_net":total_adjustments,
        "sold_units_total":sold_units,
    }

@router.get("/api/admin/analytics")
def admin_analytics(
    days: int = Query(30, ge=0, le=3650),
    postal_code: str = "",
    assigned_user_id: Optional[int] = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    start = _period_start(days)
    postal_code = postal_code.strip()
    postal_cond = Lead.postal_code == postal_code if postal_code else None
    rep_cond = Lead.assigned_user_id == assigned_user_id if assigned_user_id else None

    all_postal_codes = list(db.scalars(
        select(Lead.postal_code)
        .where(Lead.postal_code.is_not(None), Lead.postal_code != "")
        .distinct()
        .order_by(Lead.postal_code.asc())
    ).all())

    lead_count_q = select(func.count()).select_from(Lead)
    won_q = select(func.count()).select_from(Lead).where(Lead.status == "won")
    if postal_cond is not None:
        lead_count_q = lead_count_q.where(postal_cond)
        won_q = won_q.where(postal_cond)
    if rep_cond is not None:
        lead_count_q = lead_count_q.where(rep_cond)
        won_q = won_q.where(rep_cond)
    lead_count = db.scalar(lead_count_q) or 0
    won_leads = db.scalar(won_q) or 0
    active_users = db.scalar(select(func.count()).select_from(User).where(User.is_active == True)) or 0

    lead_period_q = select(func.count()).select_from(Lead)
    activity_period_q = (
        select(
            func.count(Activity.id),
            func.sum(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES), 1), else_=0)),
            func.sum(case((Activity.activity_type == "demo", 1), else_=0)),
            func.sum(case((Activity.activity_type == "follow_up", 1), else_=0)),
            func.count(func.distinct(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES), Activity.lead_id), else_=None))),
        )
        .select_from(Activity)
    )
    sales_period_q = (
        select(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.quantity), 0),
            func.coalesce(func.sum(Sale.total), 0),
        )
        .select_from(Sale)
    )
    activity_joined=False
    sales_joined=False
    if postal_cond is not None:
        lead_period_q = lead_period_q.where(postal_cond)
        activity_period_q = activity_period_q.join(Lead, Lead.id == Activity.lead_id).where(postal_cond)
        sales_period_q = sales_period_q.join(Lead, Lead.id == Sale.lead_id).where(postal_cond)
        activity_joined=True
        sales_joined=True
    if rep_cond is not None:
        lead_period_q = lead_period_q.where(rep_cond)
        if not activity_joined:
            activity_period_q = activity_period_q.join(Lead, Lead.id == Activity.lead_id)
            activity_joined=True
        if not sales_joined:
            sales_period_q = sales_period_q.join(Lead, Lead.id == Sale.lead_id)
            sales_joined=True
        activity_period_q = activity_period_q.where(rep_cond)
        sales_period_q = sales_period_q.where(rep_cond)
    if start:
        lead_period_q = lead_period_q.where(Lead.created_at >= start)
        activity_period_q = activity_period_q.where(Activity.created_at >= start)
        sales_period_q = sales_period_q.where(Sale.created_at >= start)

    new_leads = db.scalar(lead_period_q) or 0
    activity_totals = db.execute(activity_period_q).one()
    activity_count = int(activity_totals[0] or 0)
    visits = int(activity_totals[1] or 0)
    demos = int(activity_totals[2] or 0)
    followups = int(activity_totals[3] or 0)
    visited_businesses = int(activity_totals[4] or 0)
    sales_total = db.execute(sales_period_q).one()
    sales = int(sales_total[0] or 0)
    units = int(sales_total[1] or 0)
    revenue = float(sales_total[2] or 0)

    comparison=None
    if start and days>0:
        period_end=utcnow()
        span=period_end-start
        if days==1:
            prev_start=start-timedelta(days=1)
            prev_end=prev_start+span
        else:
            prev_start=start-span
            prev_end=start

        prev_leads_q=select(func.count()).select_from(Lead).where(Lead.created_at>=prev_start,Lead.created_at<prev_end)
        prev_activity_q=select(
            func.sum(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES),1),else_=0))
        ).select_from(Activity).where(Activity.created_at>=prev_start,Activity.created_at<prev_end)
        prev_sales_q=select(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.total),0)
        ).select_from(Sale).where(Sale.created_at>=prev_start,Sale.created_at<prev_end)

        prev_activity_joined=False
        prev_sales_joined=False
        if postal_cond is not None:
            prev_leads_q=prev_leads_q.where(postal_cond)
            prev_activity_q=prev_activity_q.join(Lead,Lead.id==Activity.lead_id).where(postal_cond)
            prev_sales_q=prev_sales_q.join(Lead,Lead.id==Sale.lead_id).where(postal_cond)
            prev_activity_joined=True
            prev_sales_joined=True
        if rep_cond is not None:
            prev_leads_q=prev_leads_q.where(rep_cond)
            if not prev_activity_joined:
                prev_activity_q=prev_activity_q.join(Lead,Lead.id==Activity.lead_id)
            if not prev_sales_joined:
                prev_sales_q=prev_sales_q.join(Lead,Lead.id==Sale.lead_id)
            prev_activity_q=prev_activity_q.where(rep_cond)
            prev_sales_q=prev_sales_q.where(rep_cond)

        prev_leads=int(db.scalar(prev_leads_q) or 0)
        prev_visits=int(db.scalar(prev_activity_q) or 0)
        prev_sales_row=db.execute(prev_sales_q).one()
        prev_sales=int(prev_sales_row[0] or 0)
        prev_revenue=float(prev_sales_row[1] or 0)

        def delta_pct(current,previous):
            if not previous:
                return None
            return round(((current-previous)/previous)*100,1)

        comparison={
            "previous":{"new_leads":prev_leads,"visits":prev_visits,"sales":prev_sales,"revenue":prev_revenue},
            "delta_pct":{
                "new_leads":delta_pct(new_leads,prev_leads),
                "visits":delta_pct(visits,prev_visits),
                "sales":delta_pct(sales,prev_sales),
                "revenue":delta_pct(revenue,prev_revenue)
            }
        }

    status_q = select(Lead.status, func.count(Lead.id)).group_by(Lead.status).order_by(func.count(Lead.id).desc())
    if postal_cond is not None:
        status_q = status_q.where(postal_cond)
    if rep_cond is not None:
        status_q = status_q.where(rep_cond)
    status_rows = db.execute(status_q).all()
    statuses = [{
        "status": status,
        "label": STATUS_LABELS.get(status, status),
        "count": int(count or 0),
        "pct": round((int(count or 0) / lead_count * 100), 1) if lead_count else 0,
    } for status, count in status_rows]

    def breakdown(dim, key_name):
        base_q = (
            select(
                dim,
                func.count(Lead.id),
                func.sum(case((Lead.status == "won", 1), else_=0)),
            )
            .select_from(Lead)
        )
        aq = (
            select(
                dim,
                func.sum(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES), 1), else_=0)),
                func.sum(case((Activity.activity_type == "demo", 1), else_=0)),
                func.sum(case((Activity.activity_type == "follow_up", 1), else_=0)),
            )
            .select_from(Activity)
            .join(Lead, Lead.id == Activity.lead_id)
        )
        sq = (
            select(
                dim,
                func.count(Sale.id),
                func.coalesce(func.sum(Sale.quantity), 0),
                func.coalesce(func.sum(Sale.total), 0),
            )
            .select_from(Sale)
            .join(Lead, Lead.id == Sale.lead_id)
        )
        if postal_cond is not None:
            base_q = base_q.where(postal_cond)
            aq = aq.where(postal_cond)
            sq = sq.where(postal_cond)
        if rep_cond is not None:
            base_q = base_q.where(rep_cond)
            aq = aq.where(rep_cond)
            sq = sq.where(rep_cond)
        if start:
            aq = aq.where(Activity.created_at >= start)
            sq = sq.where(Sale.created_at >= start)
        base_rows = db.execute(base_q.group_by(dim)).all()
        activity_rows = db.execute(aq.group_by(dim)).all()
        sale_rows = db.execute(sq.group_by(dim)).all()
        return _merge_breakdown(base_rows, activity_rows, sale_rows, key_name)

    postal_codes = breakdown(Lead.postal_code, "postal_code")
    for row in postal_codes:
        row.update(postal_zone(row["postal_code"]))
    categories = breakdown(Lead.business_type, "category")

    now=utcnow()
    day_start,day_end=madrid_day_bounds()
    alert_base=[Lead.status.in_(["pending","owner_absent","closed","follow_up"])]
    if postal_cond is not None:
        alert_base.append(postal_cond)
    if rep_cond is not None:
        alert_base.append(rep_cond)
    open_deals=db.scalar(select(func.count()).select_from(Lead).where(*alert_base)) or 0
    followups_today=db.scalar(select(func.count()).select_from(Lead).where(
        *alert_base,
        Lead.status=="follow_up",
        Lead.follow_up_at.is_not(None),
        Lead.follow_up_at>=day_start,
        Lead.follow_up_at<=day_end
    )) or 0
    overdue_followups=db.scalar(select(func.count()).select_from(Lead).where(
        *alert_base,
        Lead.status=="follow_up",
        Lead.follow_up_at.is_not(None),
        Lead.follow_up_at<now
    )) or 0
    stale_cutoff=now-timedelta(days=7)
    stale_condition=or_(
        (Lead.status.in_(["pending","owner_absent","closed"])) & (Lead.updated_at<stale_cutoff),
        (Lead.status=="follow_up") & (Lead.follow_up_at.is_(None)) & (Lead.updated_at<stale_cutoff)
    )
    stale_q=select(func.count()).select_from(Lead).where(stale_condition)
    if postal_cond is not None:
        stale_q=stale_q.where(postal_cond)
    if rep_cond is not None:
        stale_q=stale_q.where(rep_cond)
    stale_active_leads=db.scalar(stale_q) or 0

    open_followup_filters=[
        Lead.status=="follow_up"
    ]
    if postal_cond is not None:
        open_followup_filters.append(postal_cond)
    if rep_cond is not None:
        open_followup_filters.append(rep_cond)
    open_followups=db.scalar(select(func.count()).select_from(Lead).where(*open_followup_filters)) or 0
    scheduled_followups=db.scalar(select(func.count()).select_from(Lead).where(
        *open_followup_filters,
        Lead.follow_up_at.is_not(None)
    )) or 0
    followup_scheduled_pct=round((scheduled_followups/open_followups*100),1) if open_followups else 0
    followup_overdue_pct=round((overdue_followups/scheduled_followups*100),1) if scheduled_followups else 0

    open_updated=list(db.scalars(
        select(Lead.updated_at).where(*alert_base)
    ).all())
    aging={"0_2":0,"3_7":0,"8_14":0,"15_plus":0}
    age_days=[]
    for dt in open_updated:
        d=max(0,(now-dt).days)
        age_days.append(d)
        if d<=2:
            aging["0_2"]+=1
        elif d<=7:
            aging["3_7"]+=1
        elif d<=14:
            aging["8_14"]+=1
        else:
            aging["15_plus"]+=1
    avg_open_age_days=round(sum(age_days)/len(age_days),1) if age_days else 0

    decided_filters=[Lead.status.in_(["won","lost"])]
    if postal_cond is not None:
        decided_filters.append(postal_cond)
    if rep_cond is not None:
        decided_filters.append(rep_cond)
    decided_rows=db.execute(
        select(
            func.sum(case((Lead.status=="won",1),else_=0)),
            func.sum(case((Lead.status=="lost",1),else_=0))
        ).where(*decided_filters)
    ).one()
    decided_won=int(decided_rows[0] or 0)
    decided_lost=int(decided_rows[1] or 0)
    decided_total=decided_won+decided_lost
    decision_win_rate_pct=round((decided_won/decided_total*100),1) if decided_total else 0

    sale_cycle_q=select(Sale.created_at,Lead.created_at).join(Lead,Lead.id==Sale.lead_id)
    if postal_cond is not None:
        sale_cycle_q=sale_cycle_q.where(postal_cond)
    if rep_cond is not None:
        sale_cycle_q=sale_cycle_q.where(rep_cond)
    if start:
        sale_cycle_q=sale_cycle_q.where(Sale.created_at>=start)
    sale_cycles=[
        max(0,(sale_at-lead_at).total_seconds()/86400)
        for sale_at,lead_at in db.execute(sale_cycle_q).all()
        if sale_at and lead_at
    ]
    avg_days_to_sale=round(sum(sale_cycles)/len(sale_cycles),1) if sale_cycles else 0

    coverage_q=select(Lead.postal_code).where(Lead.postal_code.in_(list(COVERAGE_POSTAL_CODES)))
    if rep_cond is not None:
        coverage_q=coverage_q.where(rep_cond)
    covered_cps=set(db.scalars(coverage_q.distinct()).all())
    territory_total=len(COVERAGE_POSTAL_CODES)
    territory_coverage_pct=round((len(covered_cps)/territory_total*100),1) if territory_total else 0
    whitespace=[
        postal_zone(cp) for cp in sorted(COVERAGE_POSTAL_CODES)
        if cp not in covered_cps
    ]

    attention_q=(
        select(Lead,User.email)
        .join(User,User.id==Lead.assigned_user_id)
        .where(or_(
            (Lead.status=="follow_up") & (Lead.follow_up_at.is_not(None)) & (Lead.follow_up_at<now),
            stale_condition
        ))
    )
    if postal_cond is not None:
        attention_q=attention_q.where(postal_cond)
    if rep_cond is not None:
        attention_q=attention_q.where(rep_cond)
    attention_rows=db.execute(
        attention_q.order_by(
            case(((Lead.status=="follow_up") & (Lead.follow_up_at.is_not(None)) & (Lead.follow_up_at<now),0),else_=1),
            Lead.follow_up_at.asc().nulls_last(),
            Lead.updated_at.asc()
        ).limit(20)
    ).all()
    attention=[]
    for lead,email in attention_rows:
        overdue=lead.status=="follow_up" and lead.follow_up_at is not None and lead.follow_up_at<now
        zi=postal_zone(lead.postal_code)
        attention.append({
            "id":lead.id,
            "name":lead.name,
            "postal_code":lead.postal_code,
            "zone_short":zi["zone_short"],
            "rep_email":email,
            "status":lead.status,
            "reason":"Seguimiento vencido" if overdue else "Sin tocar 7+ días",
            "follow_up_at":lead.follow_up_at.isoformat() if lead.follow_up_at else None,
            "updated_at":lead.updated_at.isoformat()
        })

    users = list(db.scalars(select(User).order_by(User.created_at.asc())).all())
    reps = []
    for u in users:
        leads_q = select(func.count()).select_from(Lead).where(Lead.assigned_user_id == u.id)
        won_rep_q = select(func.count()).select_from(Lead).where(Lead.assigned_user_id == u.id, Lead.status == "won")
        open_rep_q = select(func.count()).select_from(Lead).where(Lead.assigned_user_id == u.id,Lead.status.in_(["pending","owner_absent","closed","follow_up"]))
        overdue_rep_q = select(func.count()).select_from(Lead).where(
            Lead.assigned_user_id == u.id,
            Lead.status=="follow_up",
            Lead.follow_up_at.is_not(None),
            Lead.follow_up_at<now
        )
        last_activity_q=select(func.max(Activity.created_at)).where(Activity.actor_user_id==u.id)
        aq = (
            select(
                func.sum(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES), 1), else_=0)),
                func.sum(case((Activity.activity_type == "demo", 1), else_=0)),
                func.sum(case((Activity.activity_type == "follow_up", 1), else_=0)),
                func.count(func.distinct(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES), Activity.lead_id), else_=None))),
            )
            .select_from(Activity)
            .where(Activity.actor_user_id == u.id)
        )
        sq = (
            select(
                func.count(Sale.id),
                func.coalesce(func.sum(Sale.quantity), 0),
                func.coalesce(func.sum(Sale.total), 0),
            )
            .select_from(Sale)
            .where(Sale.actor_user_id == u.id)
        )
        if postal_cond is not None:
            leads_q = leads_q.where(postal_cond)
            won_rep_q = won_rep_q.where(postal_cond)
            open_rep_q = open_rep_q.where(postal_cond)
            overdue_rep_q = overdue_rep_q.where(postal_cond)
            aq = aq.join(Lead, Lead.id == Activity.lead_id).where(postal_cond)
            sq = sq.join(Lead, Lead.id == Sale.lead_id).where(postal_cond)
            last_activity_q = last_activity_q.join(Lead, Lead.id == Activity.lead_id).where(postal_cond)
        if start:
            aq = aq.where(Activity.created_at >= start)
            sq = sq.where(Sale.created_at >= start)

        leads = db.scalar(leads_q) or 0
        won = db.scalar(won_rep_q) or 0
        open_rep = db.scalar(open_rep_q) or 0
        overdue_rep = db.scalar(overdue_rep_q) or 0
        last_activity = db.scalar(last_activity_q)
        ar = db.execute(aq).one()
        sr = db.execute(sq).one()
        rep_sales = int(sr[0] or 0)
        rep_revenue = float(sr[2] or 0)
        rep_visits = int(ar[0] or 0)
        rep_visited_businesses = int(ar[3] or 0)
        is_admin = u.role == "admin" or u.email.lower() == ADMIN_EMAIL
        reps.append({
            "id": u.id,
            "email": u.email,
            "role": "admin" if is_admin else u.role,
            "is_active": u.is_active,
            "leads": int(leads),
            "won": int(won),
            "open_leads":int(open_rep),
            "overdue_followups":int(overdue_rep),
            "last_activity_at":last_activity.isoformat() if last_activity else None,
            "visits": rep_visits,
            "visited_businesses":rep_visited_businesses,
            "demos": int(ar[1] or 0),
            "followups": int(ar[2] or 0),
            "sales": rep_sales,
            "units": int(sr[1] or 0),
            "revenue": rep_revenue,
            "conversion_pct": round((won / leads * 100), 1) if leads else 0,
            "sale_per_visit_pct": round((rep_sales / rep_visited_businesses * 100), 1) if rep_visited_businesses else 0,
            "avg_ticket": round((rep_revenue / rep_sales), 2) if rep_sales else 0,
        })

    trend_days = 30 if days == 0 else min(max(days, 1), 90)
    trend_start = utcnow() - timedelta(days=trend_days - 1)
    lead_daily_q = (
        select(func.date(Lead.created_at), func.count(Lead.id))
        .where(Lead.created_at >= trend_start)
    )
    activity_daily_q = (
        select(
            func.date(Activity.created_at),
            func.sum(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES), 1), else_=0)),
            func.sum(case((Activity.activity_type == "demo", 1), else_=0)),
        )
        .select_from(Activity)
        .where(Activity.created_at >= trend_start)
    )
    sales_daily_q = (
        select(
            func.date(Sale.created_at),
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.total), 0),
        )
        .select_from(Sale)
        .where(Sale.created_at >= trend_start)
    )
    activity_daily_joined=False
    sales_daily_joined=False
    if postal_cond is not None:
        lead_daily_q = lead_daily_q.where(postal_cond)
        activity_daily_q = activity_daily_q.join(Lead, Lead.id == Activity.lead_id).where(postal_cond)
        sales_daily_q = sales_daily_q.join(Lead, Lead.id == Sale.lead_id).where(postal_cond)
        activity_daily_joined=True
        sales_daily_joined=True
    if rep_cond is not None:
        lead_daily_q=lead_daily_q.where(rep_cond)
        if not activity_daily_joined:
            activity_daily_q=activity_daily_q.join(Lead,Lead.id==Activity.lead_id)
        if not sales_daily_joined:
            sales_daily_q=sales_daily_q.join(Lead,Lead.id==Sale.lead_id)
        activity_daily_q=activity_daily_q.where(rep_cond)
        sales_daily_q=sales_daily_q.where(rep_cond)

    lead_daily = db.execute(lead_daily_q.group_by(func.date(Lead.created_at))).all()
    activity_daily = db.execute(activity_daily_q.group_by(func.date(Activity.created_at))).all()
    sales_daily = db.execute(sales_daily_q.group_by(func.date(Sale.created_at))).all()
    daily = {}
    for i in range(trend_days):
        d = (trend_start + timedelta(days=i)).date().isoformat()
        daily[d] = {"date": d, "leads": 0, "visits": 0, "demos": 0, "sales": 0, "revenue": 0.0}
    for d, n in lead_daily:
        daily[str(d)]["leads"] = int(n or 0)
    for d, v, dm in activity_daily:
        daily[str(d)]["visits"] = int(v or 0)
        daily[str(d)]["demos"] = int(dm or 0)
    for d, s, rev in sales_daily:
        daily[str(d)]["sales"] = int(s or 0)
        daily[str(d)]["revenue"] = float(rev or 0)

    recent_q = (
        select(AuditLog, User.email, Lead.name)
        .join(User, User.id == AuditLog.actor_user_id)
        .outerjoin(Lead, Lead.id == AuditLog.lead_id)
    )
    if postal_cond is not None:
        recent_q = recent_q.where(postal_cond)
    if assigned_user_id:
        recent_q=recent_q.where(AuditLog.actor_user_id==assigned_user_id)
    recent_rows = db.execute(recent_q.order_by(AuditLog.created_at.desc()).limit(50)).all()
    recent = [{
        "event_type": log.event_type,
        "created_at": log.created_at.isoformat(),
        "user_email": email,
        "lead_name": lead_name or "",
    } for log, email, lead_name in recent_rows]

    insights=[]
    if overdue_followups:
        insights.append({
            "level":"danger",
            "title":f"{overdue_followups} seguimientos vencidos",
            "body":"Prioriza estos deals antes de seguir abriendo cartera nueva."
        })
    if stale_active_leads:
        insights.append({
            "level":"warning",
            "title":f"{stale_active_leads} deals abiertos sin tocar en 7+ días",
            "body":"Revisa si deben reactivarse, reprogramarse o cerrarse."
        })
    if comparison and comparison["delta_pct"]["revenue"] is not None:
        delta=comparison["delta_pct"]["revenue"]
        direction="sube" if delta>=0 else "baja"
        insights.append({
            "level":"positive" if delta>=0 else "warning",
            "title":f"La facturación {direction} {abs(delta):.1f}% vs. el periodo anterior",
            "body":f"Periodo actual: {revenue:.2f} € · periodo anterior: {comparison['previous']['revenue']:.2f} €."
        })
    zero_sale_zones=[x for x in postal_codes if x.get("visits",0)>=3 and x.get("sales",0)==0]
    if zero_sale_zones:
        z=sorted(zero_sale_zones,key=lambda x:x.get("visits",0),reverse=True)[0]
        insights.append({
            "level":"focus",
            "title":f"{z['postal_code']} acumula {z['visits']} visitas sin venta",
            "body":z.get("zone_short") or z.get("zone_label") or "Revisar enfoque comercial de la zona."
        })
    if postal_codes:
        top_zone=max(postal_codes,key=lambda x:x.get("revenue",0))
        if top_zone.get("revenue",0)>0:
            insights.append({
                "level":"positive",
                "title":f"{top_zone['postal_code']} lidera la facturación por zona",
                "body":f"{top_zone.get('zone_short','')} · {top_zone.get('sales',0)} ventas · {top_zone.get('revenue',0):.2f} €."
            })
    if categories:
        top_cat=max(categories,key=lambda x:x.get("revenue",0))
        if top_cat.get("revenue",0)>0:
            insights.append({
                "level":"focus",
                "title":f"{top_cat['category']} es la categoría con más facturación",
                "body":f"{top_cat.get('sales',0)} ventas · {top_cat.get('revenue',0):.2f} € en el periodo."
            })
    if territory_coverage_pct<100:
        insights.append({
            "level":"info",
            "title":f"Cobertura territorial objetivo: {territory_coverage_pct:.1f}%",
            "body":f"{territory_total-len(covered_cps)} CP de Barcelona + Sant Cugat + Rubí todavía sin ningún deal registrado."
        })
    insights=insights[:6]

    inventory_net=int(db.scalar(select(func.coalesce(func.sum(InventoryMovement.quantity_delta),0))) or 0)
    sold_units_total=int(db.scalar(select(func.coalesce(func.sum(Sale.quantity),0))) or 0)
    stock_available=inventory_net-sold_units_total
    inventory_added=int(db.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity_delta),0))
        .where(InventoryMovement.quantity_delta>0)
    ) or 0)

    return {
        "period": {"days": days, "start": start.isoformat() if start else None},
        "segment": {"postal_code": postal_code or None,"assigned_user_id":assigned_user_id},
        "available_postal_codes": all_postal_codes,
        "postal_directory":[postal_zone(cp) for cp in sorted(POSTAL_ZONE_MAP.keys())],
        "coverage_postal_codes":sorted(COVERAGE_POSTAL_CODES),
        "summary": {
            "active_users": int(active_users),
            "open_deals":int(open_deals),
            "followups_today":int(followups_today),
            "overdue_followups":int(overdue_followups),
            "stale_active_leads":int(stale_active_leads),
            "leads_total": int(lead_count),
            "won_total": int(won_leads),
            "portfolio_conversion_pct": round((won_leads / lead_count * 100), 1) if lead_count else 0,
            "new_leads": int(new_leads),
            "activities": activity_count,
            "visits": visits,
            "visited_businesses":visited_businesses,
            "demos": demos,
            "followups": followups,
            "sales": sales,
            "units": units,
            "revenue": revenue,
            "avg_ticket": round((revenue / sales), 2) if sales else 0,
            "sale_per_visit_pct": round((sales / visited_businesses * 100), 1) if visited_businesses else 0,
            "revenue_per_visit": round((revenue / visits), 2) if visits else 0,
            "revenue_per_lead": round((revenue / lead_count), 2) if lead_count else 0,
            "decision_win_rate_pct":decision_win_rate_pct,
            "avg_days_to_sale":avg_days_to_sale,
            "followup_scheduled_pct":followup_scheduled_pct,
            "followup_overdue_pct":followup_overdue_pct,
            "avg_open_age_days":avg_open_age_days,
            "territory_coverage_pct":territory_coverage_pct,
            "covered_postal_codes":len(covered_cps),
            "territory_total_postal_codes":territory_total,
            "stock_available":stock_available,
            "stock_units_added":inventory_added,
            "stock_adjustment_net":inventory_net,
            "sold_units_total":sold_units_total,
        },
        "comparison":comparison,
        "pipeline_aging":aging,
        "whitespace":whitespace[:15],
        "insights":insights,
        "statuses": statuses,
        "postal_codes": postal_codes,
        "categories": categories,
        "reps": reps,
        "daily": list(daily.values()),
        "attention":attention,
        "recent": recent,
    }

@router.get("/api/admin/summary")
def admin_summary(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    data = admin_analytics(days=1, admin=admin, db=db)
    s = data["summary"]
    return {
        "active_users": s["active_users"],
        "leads": s["leads_total"],
        "won_leads": s["won_total"],
        "conversion_pct": s["portfolio_conversion_pct"],
        "visits_today": s["visits"],
        "demos_today": s["demos"],
        "sales_today": s["sales"],
        "revenue_today": s["revenue"],
        "sales_total": db.scalar(select(func.count()).select_from(Sale)) or 0,
        "revenue_total": float(db.scalar(select(func.coalesce(func.sum(Sale.total), 0))) or 0),
        "postal_codes": [{"postal_code": x["postal_code"], "leads": x["leads"]} for x in data["postal_codes"][:8]],
        "categories": [{"category": x["category"], "leads": x["leads"]} for x in data["categories"][:8]],
    }

@router.get("/api/admin/reps")
def admin_reps(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"items": admin_analytics(days=0, admin=admin, db=db)["reps"]}

@router.post("/api/admin/users")
def create_commercial(data: AdminUserCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email))
    if existing:
        raise HTTPException(status_code=409, detail="Ya existe un usuario con ese email")
    user = User(email=email, password_hash=hash_password(data.temporary_password), role="commercial", is_active=True)
    db.add(user)
    db.flush()
    db.add(AuditLog(actor_user_id=admin.id, lead_id=None, event_type="commercial_created", payload='{"commercial_user_id": %d}' % user.id))
    db.commit()
    return {"id": user.id, "email": user.email, "role": user.role, "is_active": user.is_active}

@router.post("/api/admin/users/{user_id}/reset-password")
def reset_commercial_password(user_id: int, data: AdminPasswordReset, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    target.password_hash = hash_password(data.new_password)
    db.add(AuditLog(actor_user_id=admin.id, lead_id=None, event_type="commercial_password_reset", payload='{"commercial_user_id": %d}' % target.id))
    db.commit()
    return {"ok": True}

@router.patch("/api/admin/users/{user_id}/active")
def set_commercial_active(user_id: int, data: ActivePatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if target.id == admin.id and not data.is_active:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propio usuario administrador")
    target.is_active = data.is_active
    db.add(AuditLog(actor_user_id=admin.id, lead_id=None, event_type="commercial_access_changed", payload='{"commercial_user_id": %d, "is_active": %s}' % (target.id, str(data.is_active).lower())))
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
    conditions = _lead_filters(search, postal_code, business_type, status, assigned_user_id)
    q = select(Lead).where(*conditions)
    count_q = select(func.count()).select_from(Lead).where(*conditions)
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

    ids = [x.id for x in rows]
    visits = {}
    demos = {}
    sales = {}
    units = {}
    revenue = {}
    if ids:
        for lead_id, v, d in db.execute(
            select(
                Activity.lead_id,
                func.sum(case((Activity.activity_type.in_(VISIT_ACTIVITY_TYPES), 1), else_=0)),
                func.sum(case((Activity.activity_type == "demo", 1), else_=0)),
            )
            .where(Activity.lead_id.in_(ids))
            .group_by(Activity.lead_id)
        ).all():
            visits[lead_id] = int(v or 0)
            demos[lead_id] = int(d or 0)
        for lead_id, s, u, r in db.execute(
            select(Sale.lead_id, func.count(Sale.id), func.coalesce(func.sum(Sale.quantity),0), func.coalesce(func.sum(Sale.total),0))
            .where(Sale.lead_id.in_(ids))
            .group_by(Sale.lead_id)
        ).all():
            sales[lead_id] = int(s or 0)
            units[lead_id] = int(u or 0)
            revenue[lead_id] = float(r or 0)

    items = []
    for x in rows:
        s = sales.get(x.id, 0)
        rev = revenue.get(x.id, 0.0)
        items.append({
            "id": x.id,
            "name": x.name,
            "address": x.address or "",
            "postal_code": x.postal_code,
            "zone_label": postal_zone(x.postal_code)["zone_label"],
            "zone_short": postal_zone(x.postal_code)["zone_short"],
            "business_type": x.business_type,
            "business_subtype": x.business_subtype or "",
            "owner_name": x.owner_name or "",
            "phone": x.phone or "",
            "status": x.status,
            "next_action": x.next_action or "",
            "follow_up_at":x.follow_up_at.isoformat() if x.follow_up_at else None,
            "assigned_user_id": x.assigned_user_id,
            "rep_email": emails.get(x.assigned_user_id, ""),
            "created_at": x.created_at.isoformat(),
            "updated_at": x.updated_at.isoformat(),
            "visits": visits.get(x.id, 0),
            "demos": demos.get(x.id, 0),
            "sales": s,
            "units": units.get(x.id, 0),
            "revenue": rev,
            "avg_ticket": round((rev / s), 2) if s else 0,
        })

    return {
        "items": items,
        "total_filtered": int(db.scalar(count_q) or 0),
        "next_cursor": _encode_cursor(rows[-1]) if has_more and rows else None,
    }

@router.post("/api/account/password")
def change_own_password(data: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="La contraseña actual no es correcta")
    user.password_hash = hash_password(data.new_password)
    db.add(AuditLog(actor_user_id=user.id, lead_id=None, event_type="password_changed", payload="{}"))
    db.commit()
    return {"ok": True}
