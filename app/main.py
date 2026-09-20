import os, json, base64
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select, text, case
from sqlalchemy.orm import Session
from .db import Base, engine, SessionLocal, User, Lead, Activity, Sale, AuditLog, IdempotencyKey, utcnow
from .auth import hash_password, verify_password, sign_token, get_db, current_user
from .schemas import LoginIn, LeadCreate, LeadPatch, ActivityCreate, SaleCreate

APP_ENV=os.getenv('APP_ENV','development'); SEED=os.getenv('SEED_DEMO_LEAD','true').lower()=='true'
VALID_STATUSES={'pending','owner_absent','closed','follow_up','won','lost'}
VALID_ACTIVITIES={'visit','demo','follow_up','owner_absent','closed','no_interest','note'}

def lead_out(x:Lead):
    return {'id':x.id,'name':x.name,'address':x.address or '','postal_code':x.postal_code,'business_type':x.business_type,
            'business_subtype':x.business_subtype or '','owner_name':x.owner_name or '','phone':x.phone or '',
            'status':x.status,'next_action':x.next_action or '','created_at':x.created_at.isoformat(),'updated_at':x.updated_at.isoformat()}
def audit(db,user,event,lead_id=None,payload=None): db.add(AuditLog(actor_user_id=user,lead_id=lead_id,event_type=event,payload=json.dumps(payload or {},ensure_ascii=False)))
def _b64(b:bytes)->str:return base64.urlsafe_b64encode(b).decode().rstrip('=')
def _b64d(s:str)->bytes:return base64.urlsafe_b64decode((s+'='*(-len(s)%4)).encode())
def encode_cursor(x:Lead)->str:return _b64(f'{int(x.updated_at.timestamp()*1000000)}:{x.id}'.encode())
def decode_cursor(c:str):
    try:
        micros,lid=_b64d(c).decode().split(':',1); return datetime.fromtimestamp(int(micros)/1_000_000,tz=timezone.utc),int(lid)
    except Exception: raise HTTPException(400,'Cursor no válido')

app=FastAPI(title='Revify CRM',version='1.0.0')
@app.on_event('startup')
def startup():
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        if engine.dialect.name=='postgresql':
            try:
                conn.execute(text('CREATE EXTENSION IF NOT EXISTS pg_trgm'))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_name_trgm ON leads USING gin (lower(name) gin_trgm_ops)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_leads_subtype_trgm ON leads USING gin (lower(coalesce(business_subtype,'')) gin_trgm_ops)"))
            except Exception: pass
    email=os.getenv('REVIFY_USER_EMAIL','demo@revify.local'); password=os.getenv('REVIFY_USER_PASSWORD','demo')
    if APP_ENV=='production' and (email=='demo@revify.local' or password=='demo'): raise RuntimeError('Configura credenciales de producción')
    with SessionLocal() as db:
        user=db.scalar(select(User).where(User.email==email.lower()))
        if not user:
            user=User(email=email.lower(),password_hash=hash_password(password),role='commercial'); db.add(user); db.flush()
        if SEED and not (db.scalar(select(func.count()).select_from(Lead).where(Lead.assigned_user_id==user.id)) or 0):
            db.add(Lead(assigned_user_id=user.id,name='Ferretería Demo',address='Carrer de Mallorca, 100',postal_code='08036',business_type='Comercio / Retail',business_subtype='Ferretería',owner_name='Demo',status='pending',next_action='Primera visita pendiente'))
        db.commit()

@app.get('/api/health')
def health():
    with SessionLocal() as db: db.execute(text('SELECT 1'))
    return {'ok':True,'time':utcnow().isoformat()}
@app.post('/api/login')
def login(data:LoginIn,db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==data.email.lower()))
    if not user or not verify_password(data.password,user.password_hash): raise HTTPException(401,'Email o contraseña incorrectos')
    return {'access_token':sign_token(user.id),'user':{'id':user.id,'email':user.email,'role':user.role}}
@app.get('/api/me')
def me(user:User=Depends(current_user)): return {'id':user.id,'email':user.email,'role':user.role}
@app.get('/api/metrics')
def metrics(user:User=Depends(current_user),db:Session=Depends(get_db)):
    today=utcnow().replace(hour=0,minute=0,second=0,microsecond=0)
    visits=db.scalar(select(func.count()).select_from(Activity).where(Activity.actor_user_id==user.id,Activity.activity_type=='visit',Activity.created_at>=today)) or 0
    demos=db.scalar(select(func.count()).select_from(Activity).where(Activity.actor_user_id==user.id,Activity.activity_type=='demo',Activity.created_at>=today)) or 0
    sales=db.scalar(select(func.count()).select_from(Sale).where(Sale.actor_user_id==user.id,Sale.created_at>=today)) or 0
    revenue=db.scalar(select(func.coalesce(func.sum(Sale.total),0)).where(Sale.actor_user_id==user.id,Sale.created_at>=today)) or 0
    priority=db.scalar(select(Lead).where(Lead.assigned_user_id==user.id,Lead.status.in_(['follow_up','owner_absent','pending','closed'])).order_by(case((Lead.status=='follow_up',0),(Lead.status=='owner_absent',1),(Lead.status=='pending',2),else_=3),Lead.updated_at.desc()).limit(1))
    return {'visits':visits,'demos':demos,'sales':sales,'revenue':float(revenue),'priority_lead':lead_out(priority) if priority else None}
@app.get('/api/leads')
def list_leads(search:str='',cursor:Optional[str]=None,limit:int=Query(50,ge=1,le=100),user:User=Depends(current_user),db:Session=Depends(get_db)):
    q=select(Lead).where(Lead.assigned_user_id==user.id)
    if search:
        s=f'%{search.strip().lower()}%'; q=q.where(or_(func.lower(Lead.name).like(s),func.lower(func.coalesce(Lead.address,'')).like(s),func.lower(Lead.postal_code).like(s),func.lower(Lead.business_type).like(s),func.lower(func.coalesce(Lead.business_subtype,'')).like(s),func.lower(func.coalesce(Lead.owner_name,'')).like(s)))
    if cursor:
        dt,lid=decode_cursor(cursor); q=q.where(or_(Lead.updated_at<dt,(Lead.updated_at==dt)&(Lead.id<lid)))
    rows=list(db.scalars(q.order_by(Lead.updated_at.desc(),Lead.id.desc()).limit(limit+1)).all()); more=len(rows)>limit; rows=rows[:limit]
    base=select(func.count()).select_from(Lead).where(Lead.assigned_user_id==user.id)
    summary={'total':db.scalar(base) or 0,'pending':db.scalar(base.where(Lead.status=='pending')) or 0,'follow_up':db.scalar(base.where(Lead.status=='follow_up')) or 0,'won':db.scalar(base.where(Lead.status=='won')) or 0}
    return {'items':[lead_out(x) for x in rows],'next_cursor':encode_cursor(rows[-1]) if more and rows else None,'summary':summary}
@app.post('/api/leads')
def create_lead(data:LeadCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if data.status not in VALID_STATUSES: raise HTTPException(400,'Estado no válido')
    x=Lead(assigned_user_id=user.id,name=data.name.strip(),address=data.address.strip() or None,postal_code=data.postal_code,business_type=data.business_type.strip(),business_subtype=data.business_subtype.strip() or None,owner_name=data.owner_name.strip() or None,phone=data.phone.strip() or None,status=data.status,next_action='Primera visita pendiente')
    db.add(x); db.flush(); audit(db,user.id,'lead_created',x.id,{'status':x.status}); db.commit(); db.refresh(x); return lead_out(x)
@app.get('/api/leads/{lead_id}')
def get_lead(lead_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(Lead,lead_id)
    if not x or x.assigned_user_id!=user.id: raise HTTPException(404,'Lead no encontrado')
    return lead_out(x)
@app.patch('/api/leads/{lead_id}')
def patch_lead(lead_id:int,data:LeadPatch,user:User=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(Lead,lead_id)
    if not x or x.assigned_user_id!=user.id: raise HTTPException(404,'Lead no encontrado')
    before=x.status
    if data.status is not None:
        if data.status not in VALID_STATUSES: raise HTTPException(400,'Estado no válido')
        x.status=data.status
    if data.next_action is not None:x.next_action=data.next_action
    x.updated_at=utcnow(); audit(db,user.id,'lead_updated',x.id,{'status_before':before,'status_after':x.status}); db.commit(); db.refresh(x); return lead_out(x)
@app.post('/api/leads/{lead_id}/activities')
def add_activity(lead_id:int,data:ActivityCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
    x=db.get(Lead,lead_id)
    if not x or x.assigned_user_id!=user.id: raise HTTPException(404,'Lead no encontrado')
    if data.activity_type not in VALID_ACTIVITIES: raise HTTPException(400,'Actividad no válida')
    db.add(Activity(lead_id=x.id,actor_user_id=user.id,activity_type=data.activity_type,notes=data.notes.strip() or None)); x.updated_at=utcnow(); audit(db,user.id,'activity_created',x.id,{'type':data.activity_type}); db.commit(); return {'ok':True}
@app.post('/api/sales')
def create_sale(data:SaleCreate,idempotency_key:Optional[str]=Header(None,alias='Idempotency-Key'),user:User=Depends(current_user),db:Session=Depends(get_db)):
    if not idempotency_key: raise HTTPException(400,'Falta Idempotency-Key')
    existing=db.get(IdempotencyKey,idempotency_key)
    if existing:
        if existing.actor_user_id!=user.id: raise HTTPException(409,'Idempotency-Key ya usada')
        return json.loads(existing.response_json)
    lead=db.get(Lead,data.lead_id)
    if not lead or lead.assigned_user_id!=user.id: raise HTTPException(404,'Lead no encontrado')
    total=Decimal(data.quantity)*data.unit_price; sale=Sale(lead_id=lead.id,actor_user_id=user.id,quantity=data.quantity,unit_price=data.unit_price,total=total,payment_method=data.payment_method,delivered=data.delivered); db.add(sale); db.flush()
    lead.status='won'; lead.next_action='Venta registrada'; lead.updated_at=utcnow(); audit(db,user.id,'sale_created',lead.id,{'sale_id':sale.id,'quantity':data.quantity,'total':str(total)})
    response={'id':sale.id,'lead_id':lead.id,'quantity':sale.quantity,'unit_price':float(sale.unit_price),'total':float(sale.total)}; db.add(IdempotencyKey(key=idempotency_key,actor_user_id=user.id,response_json=json.dumps(response))); db.commit(); return response

app.mount('/static',StaticFiles(directory='static'),name='static')
@app.get('/')
def index(): return FileResponse('static/index.html')
@app.get('/{path:path}')
def spa(path:str):
    if path.startswith('api/'): raise HTTPException(404)
    return FileResponse('static/index.html')
