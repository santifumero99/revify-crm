import os, json, base64
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select, text, case
from sqlalchemy.orm import Session
from .db import Base, engine, SessionLocal, User, Lead, Activity, Sale, AuditLog, IdempotencyKey, utcnow
from .auth import hash_password, verify_password, sign_token, get_db, current_user
from .schemas import LoginIn, LeadCreate, LeadPatch, ActivityCreate, SaleCreate, SalePatch
from .admin import router as admin_router

APP_ENV=os.getenv('APP_ENV','development')
SEED=os.getenv('SEED_DEMO_LEAD','true').lower()=='true'
VALID_STATUSES={'pending','owner_absent','closed','follow_up','won','lost'}
VALID_ACTIVITIES={'visit','demo','follow_up','owner_absent','closed','no_interest','note'}
VALID_PAYMENT_METHODS={'cash','card','bizum','transfer','other'}

def lead_out(x:Lead):
    return {
        'id':x.id,'name':x.name,'address':x.address or '','postal_code':x.postal_code,
        'business_type':x.business_type,'business_subtype':x.business_subtype or '',
        'owner_name':x.owner_name or '','phone':x.phone or '','status':x.status,
        'next_action':x.next_action or '','created_at':x.created_at.isoformat(),
        'updated_at':x.updated_at.isoformat()
    }

def sale_out(x:Sale,lead:Optional[Lead]=None):
    return {
        'id':x.id,'lead_id':x.lead_id,'lead_name':lead.name if lead else '',
        'lead_address':(lead.address or '') if lead else '',
        'postal_code':lead.postal_code if lead else '',
        'quantity':x.quantity,'unit_price':float(x.unit_price),'total':float(x.total),
        'payment_method':x.payment_method,'delivered':x.delivered,
        'created_at':x.created_at.isoformat()
    }

def audit(db,user,event,lead_id=None,payload=None):
    db.add(AuditLog(actor_user_id=user,lead_id=lead_id,event_type=event,payload=json.dumps(payload or {},ensure_ascii=False)))

def _b64(b:bytes)->str:
    return base64.urlsafe_b64encode(b).decode().rstrip('=')

def _b64d(s:str)->bytes:
    return base64.urlsafe_b64decode((s+'='*(-len(s)%4)).encode())

def encode_cursor(x:Lead)->str:
    return _b64(f'{int(x.updated_at.timestamp()*1000000)}:{x.id}'.encode())

def decode_cursor(c:str):
    try:
        micros,lid=_b64d(c).decode().split(':',1)
        return datetime.fromtimestamp(int(micros)/1_000_000,tz=timezone.utc),int(lid)
    except Exception:
        raise HTTPException(400,'Cursor no válido')

app=FastAPI(title='Revify CRM',version='1.1.0')
app.include_router(admin_router)

@app.on_event('startup')
def startup():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if engine.dialect.name=='postgresql':
            try:
                conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_name_trgm ON leads USING gin (lower(name) gin_trgm_ops)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_subtype_trgm ON leads USING gin (lower(coalesce(business_subtype,'')) gin_trgm_ops)"))
            except Exception:
                pass
    email=os.getenv('REVIFY_USER_EMAIL','demo@revify.local')
    password=os.getenv('REVIFY_USER_PASSWORD','demo')
    if APP_ENV=='production' and (email=='demo@revify.local' or password=='demo'):
        raise RuntimeError('Configura credenciales de producción')
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==email.lower()))
        if not user:
            user=User(email=email.lower(),password_hash=hash_password(password),role='commercial')
            db.add(user)
            db.flush()
        if SEED and not (db.scalar(select(func.count()).select_from(Lead).where(Lead.assigned_user_id==user.id)) or 0):
            db.add(Lead(
                assigned_user_id=user.id,name='Ferretería Demo',address='Carrer de Mallorca, 100',
                postal_code='08036',business_type='Comercio / Retail',business_subtype='Ferretería',
                owner_name='Demo',status='pending',next_action='Primera visita pendiente'
            ))
        db.commit()

@app.get('/api/health')
def health():
    with SessionLocal() as db:
        db.execute(text('SELECT 1'))
    return {'ok':True,'time':utcnow().isoformat()}

@app.post('/api/login')
def login(data:LoginIn,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==data.email.lower()))
    if not user or not verify_password(data.password,user.password_hash):
        raise HTTPException(401,'Email o contraseña incorrectos')
    return {'access_token':sign_token(user.id),'user':{'id':user.id,'email':user.email,'role':user.role}}

@app.get('/api/me')
def me(user:User=Depends(current_user)):
    return {'id':user.id,'email':user.email,'role':user.role}

@app.get('/api/metrics')
def metrics(user:User=Depends(current_user),db:Session=Depends(get_db)):
    today=utcnow().replace(hour=0,minute=0,second=0,microsecond=0)
    visits=db.scalar(select(func.count()).select_from(Activity).where(Activity.actor_user_id==user.id,Activity.activity_type=='visit',Activity.created_at>=today)) or 0
    demos=db.scalar(select(func.count()).select_from(Activity).where(Activity.actor_user_id==user.id,Activity.activity_type=='demo',Activity.created_at>=today)) or 0
    sales=db.scalar(select(func.count()).select_from(Sale).where(Sale.actor_user_id==user.id,Sale.created_at>=today)) or 0
    revenue=db.scalar(select(func.coalesce(func.sum(Sale.total),0)).where(Sale.actor_user_id==user.id,Sale.created_at>=today)) or 0
    priority=db.scalar(
        select(Lead)
        .where(Lead.assigned_user_id==user.id,Lead.status.in_(['follow_up','owner_absent','pending','closed']))
        .order_by(case((Lead.status=='follow_up',0),(Lead.status=='owner_absent',1),(Lead.status=='pending',2),else_=3),Lead.updated_at.desc())
        .limit(1)
    )
    return {'visits':visits,'demos':demos,'sales':sales,'revenue':float(revenue),'priority_lead':lead_out(priority) if priority else None}

@app.get('/api/leads')
def list_leads(search:str='',cursor:Optional[str]=None,limit:int=Query(50,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    q=select(Lead).where(Lead.assigned_user_id==user.id)
    if search:
        s=f'%{search.strip().lower()}%'
        q=q.where(or_(
            func.lower(Lead.name).like(s),
            func.lower(func.coalesce(Lead.address,'')).like(s),
            func.lower(Lead.postal_code).like(s),
            func.lower(Lead.business_type).like(s),
            func.lower(func.coalesce(Lead.business_subtype,'')).like(s),
            func.lower(func.coalesce(Lead.owner_name,'')).like(s)
        ))
    if cursor:
        dt,lid=decode_cursor(cursor)
        q=q.where(or_(Lead.updated_at<dt,(Lead.updated_at==dt)&(Lead.id<lid)))
    rows=list(db.scalars(q.order_by(Lead.updated_at.desc(),Lead.id.desc()).limit(limit+1)).all())
    more=len(rows)>limit
    rows=rows[:limit]
    base=select(func.count()).select_from(Lead).where(Lead.assigned_user_id==user.id)
    total=db.scalar(base) or 0
    won=db.scalar(base.where(Lead.status=='won')) or 0
    lost=db.scalar(base.where(Lead.status=='lost')) or 0
    summary={
        'total':total,
        'pending':db.scalar(base.where(Lead.status=='pending')) or 0,
        'follow_up':db.scalar(base.where(Lead.status=='follow_up')) or 0,
        'won':won,
        'lost':lost,
        'active':max(0,total-won-lost)
    }
    return {'items':[lead_out(x) for x in rows],'next_cursor':encode_cursor(rows[-1]) if more and rows else None,'summary':summary}

@app.post('/api/leads')
def create_lead(data:LeadCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if data.status not in VALID_STATUSES:
        raise HTTPException(400,'Estado no válido')
    if data.status=='won' and data.sale_payment_method not in VALID_PAYMENT_METHODS:
        raise HTTPException(400,'Método de pago no válido')

    next_action='Venta registrada' if data.status=='won' else ('Sin venta' if data.status=='lost' else 'Primera visita pendiente')
    x=Lead(
        assigned_user_id=user.id,
        name=data.name.strip(),
        address=data.address.strip() or None,
        postal_code=data.postal_code,
        business_type=data.business_type.strip(),
        business_subtype=data.business_subtype.strip() or None,
        owner_name=data.owner_name.strip() or None,
        phone=data.phone.strip() or None,
        status=data.status,
        next_action=next_action
    )
    db.add(x)
    db.flush()
    audit(db,user.id,'lead_created',x.id,{'status':x.status})

    sale=None
    if data.status=='won':
        total=Decimal(data.sale_quantity)*data.sale_unit_price
        sale=Sale(
            lead_id=x.id,
            actor_user_id=user.id,
            quantity=data.sale_quantity,
            unit_price=data.sale_unit_price,
            total=total,
            payment_method=data.sale_payment_method,
            delivered=data.sale_delivered
        )
        db.add(sale)
        db.flush()
        audit(db,user.id,'sale_created',x.id,{'sale_id':sale.id,'quantity':sale.quantity,'total':str(total),'source':'deal_intake'})

    db.commit()
    db.refresh(x)
    response=lead_out(x)
    if sale:
        response['sale']=sale_out(sale,x)
    return response

@app.get('/api/leads/{lead_id}')
def get_lead(lead_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(Lead,lead_id)
    if not x or x.assigned_user_id!=user.id:
        raise HTTPException(404,'Lead no encontrado')
    return lead_out(x)

@app.patch('/api/leads/{lead_id}')
def patch_lead(lead_id:int,data:LeadPatch,user:User=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(Lead,lead_id)
    if not x or x.assigned_user_id!=user.id:
        raise HTTPException(404,'Lead no encontrado')

    before={
        'name':x.name,'address':x.address or '','postal_code':x.postal_code,
        'business_type':x.business_type,'business_subtype':x.business_subtype or '',
        'owner_name':x.owner_name or '','phone':x.phone or '','status':x.status,
        'next_action':x.next_action or ''
    }
    existing_sale=db.scalar(select(Sale).where(Sale.lead_id==x.id,Sale.actor_user_id==user.id).order_by(Sale.created_at.desc()).limit(1))

    if data.name is not None:
        x.name=data.name.strip()
    if data.address is not None:
        x.address=data.address.strip() or None
    if data.postal_code is not None:
        x.postal_code=data.postal_code
    if data.business_type is not None:
        x.business_type=data.business_type.strip()
    if data.business_subtype is not None:
        x.business_subtype=data.business_subtype.strip() or None
    if data.owner_name is not None:
        x.owner_name=data.owner_name.strip() or None
    if data.phone is not None:
        x.phone=data.phone.strip() or None

    sale_created=None
    if data.status is not None:
        if data.status not in VALID_STATUSES:
            raise HTTPException(400,'Estado no válido')
        if x.status=='won' and data.status!='won' and existing_sale:
            raise HTTPException(400,'Este deal ya tiene una venta. Corrige la venta desde Ventas')

        if data.status=='won' and not existing_sale:
            if data.sale_quantity is None or data.sale_unit_price is None or not data.sale_payment_method:
                raise HTTPException(400,'Completa los datos de la venta para marcarlo como vendido')
            if data.sale_payment_method not in VALID_PAYMENT_METHODS:
                raise HTTPException(400,'Método de pago no válido')
            total=Decimal(data.sale_quantity)*data.sale_unit_price
            sale_created=Sale(
                lead_id=x.id,
                actor_user_id=user.id,
                quantity=data.sale_quantity,
                unit_price=data.sale_unit_price,
                total=total,
                payment_method=data.sale_payment_method,
                delivered=True if data.sale_delivered is None else data.sale_delivered
            )
            db.add(sale_created)
            db.flush()
            audit(db,user.id,'sale_created',x.id,{'sale_id':sale_created.id,'quantity':sale_created.quantity,'total':str(total),'source':'deal_update'})
            existing_sale=sale_created

        x.status=data.status
        if x.status=='won':
            x.next_action='Venta registrada'
        elif x.status=='lost':
            x.next_action='Sin venta'
        elif x.status=='follow_up':
            x.next_action='Seguimiento pendiente'
        elif x.status=='owner_absent':
            x.next_action='Volver cuando esté el dueño'
        elif x.status=='closed':
            x.next_action='Volver a visitar'
        else:
            x.next_action='Pendiente de visita'

    if data.next_action is not None:
        x.next_action=data.next_action.strip()

    x.updated_at=utcnow()
    after={
        'name':x.name,'address':x.address or '','postal_code':x.postal_code,
        'business_type':x.business_type,'business_subtype':x.business_subtype or '',
        'owner_name':x.owner_name or '','phone':x.phone or '','status':x.status,
        'next_action':x.next_action or ''
    }
    audit(db,user.id,'lead_updated',x.id,{'before':before,'after':after})
    db.commit()
    db.refresh(x)
    response=lead_out(x)
    if sale_created:
        response['sale']=sale_out(sale_created,x)
    return response

@app.get('/api/leads/{lead_id}/activities')
def list_activities(lead_id:int,limit:int=Query(20,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(Lead,lead_id)
    if not x or x.assigned_user_id!=user.id:
        raise HTTPException(404,'Lead no encontrado')
    rows=list(db.scalars(
        select(Activity)
        .where(Activity.lead_id==x.id,Activity.actor_user_id==user.id)
        .order_by(Activity.created_at.desc(),Activity.id.desc())
        .limit(limit)
    ).all())
    return {'items':[{
        'id':a.id,
        'activity_type':a.activity_type,
        'notes':a.notes or '',
        'created_at':a.created_at.isoformat()
    } for a in rows]}

@app.post('/api/leads/{lead_id}/activities')
def add_activity(lead_id:int,data:ActivityCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(Lead,lead_id)
    if not x or x.assigned_user_id!=user.id:
        raise HTTPException(404,'Lead no encontrado')
    if data.activity_type not in VALID_ACTIVITIES:
        raise HTTPException(400,'Actividad no válida')
    db.add(Activity(lead_id=x.id,actor_user_id=user.id,activity_type=data.activity_type,notes=data.notes.strip() or None))
    x.updated_at=utcnow()
    audit(db,user.id,'activity_created',x.id,{'type':data.activity_type})
    db.commit()
    return {'ok':True}

@app.get('/api/sales')
def list_sales(limit:int=Query(100,ge=1,le=250),user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=list(db.scalars(
        select(Sale)
        .where(Sale.actor_user_id==user.id)
        .order_by(Sale.created_at.desc(),Sale.id.desc())
        .limit(limit)
    ).all())
    lead_ids={x.lead_id for x in rows}
    lead_map={}
    if lead_ids:
        lead_map={x.id:x for x in db.scalars(select(Lead).where(Lead.id.in_(lead_ids))).all()}

    count=db.scalar(select(func.count()).select_from(Sale).where(Sale.actor_user_id==user.id)) or 0
    units=db.scalar(select(func.coalesce(func.sum(Sale.quantity),0)).where(Sale.actor_user_id==user.id)) or 0
    revenue=db.scalar(select(func.coalesce(func.sum(Sale.total),0)).where(Sale.actor_user_id==user.id)) or 0
    avg_ticket=float(revenue)/count if count else 0

    return {
        'items':[sale_out(x,lead_map.get(x.lead_id)) for x in rows],
        'summary':{'sales':count,'units':int(units),'revenue':float(revenue),'avg_ticket':avg_ticket}
    }

@app.post('/api/sales')
def create_sale(data:SaleCreate,idempotency_key:Optional[str]=Header(None,alias='Idempotency-Key'),user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not idempotency_key:
        raise HTTPException(400,'Falta Idempotency-Key')
    if data.payment_method not in VALID_PAYMENT_METHODS:
        raise HTTPException(400,'Método de pago no válido')

    existing=db.get(IdempotencyKey,idempotency_key)
    if existing:
        if existing.actor_user_id!=user.id:
            raise HTTPException(409,'Idempotency-Key ya usada')
        return json.loads(existing.response_json)

    lead=db.get(Lead,data.lead_id)
    if not lead or lead.assigned_user_id!=user.id:
        raise HTTPException(404,'Lead no encontrado')

    previous_sale=db.scalar(select(Sale).where(Sale.lead_id==lead.id,Sale.actor_user_id==user.id).order_by(Sale.created_at.desc()).limit(1))
    if previous_sale:
        raise HTTPException(409,'Este lead ya tiene una venta registrada. Edítala desde Ventas')

    total=Decimal(data.quantity)*data.unit_price
    sale=Sale(
        lead_id=lead.id,
        actor_user_id=user.id,
        quantity=data.quantity,
        unit_price=data.unit_price,
        total=total,
        payment_method=data.payment_method,
        delivered=data.delivered
    )
    db.add(sale)
    db.flush()
    lead.status='won'
    lead.next_action='Venta registrada'
    lead.updated_at=utcnow()
    audit(db,user.id,'sale_created',lead.id,{'sale_id':sale.id,'quantity':data.quantity,'total':str(total),'source':'lead_close'})
    response=sale_out(sale,lead)
    db.add(IdempotencyKey(key=idempotency_key,actor_user_id=user.id,response_json=json.dumps(response)))
    db.commit()
    return response

@app.patch('/api/sales/{sale_id}')
def patch_sale(sale_id:int,data:SalePatch,user:User=Depends(current_user),db:Session=Depends(get_db)):
    sale=db.get(Sale,sale_id)
    if not sale or sale.actor_user_id!=user.id:
        raise HTTPException(404,'Venta no encontrada')

    before={
        'quantity':sale.quantity,
        'unit_price':str(sale.unit_price),
        'total':str(sale.total),
        'payment_method':sale.payment_method,
        'delivered':sale.delivered
    }

    if data.quantity is not None:
        sale.quantity=data.quantity
    if data.unit_price is not None:
        sale.unit_price=data.unit_price
    if data.payment_method is not None:
        if data.payment_method not in VALID_PAYMENT_METHODS:
            raise HTTPException(400,'Método de pago no válido')
        sale.payment_method=data.payment_method
    if data.delivered is not None:
        sale.delivered=data.delivered

    sale.total=Decimal(sale.quantity)*sale.unit_price
    lead=db.get(Lead,sale.lead_id)
    if lead:
        lead.status='won'
        lead.next_action='Venta registrada'
        lead.updated_at=utcnow()

    after={
        'quantity':sale.quantity,
        'unit_price':str(sale.unit_price),
        'total':str(sale.total),
        'payment_method':sale.payment_method,
        'delivered':sale.delivered
    }
    audit(db,user.id,'sale_updated',sale.lead_id,{'sale_id':sale.id,'before':before,'after':after})
    db.commit()
    db.refresh(sale)
    return sale_out(sale,lead)

app.mount('/static',StaticFiles(directory='static'),name='static')

@app.get('/')
def index():
    return FileResponse('static/index.html')

@app.get('/{path:path}')
def spa(path:str):
    if path.startswith('api/'):
        raise HTTPException(404)
    return FileResponse('static/index.html')
