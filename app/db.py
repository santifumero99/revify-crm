import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy import create_engine, String, Text, DateTime, ForeignKey, Numeric, Integer, Boolean, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./revify.db')
if DATABASE_URL.startswith('postgres://'):
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql+psycopg://', 1)
elif DATABASE_URL.startswith('postgresql://'):
    DATABASE_URL = DATABASE_URL.replace('postgresql://', 'postgresql+psycopg://', 1)
connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def utcnow(): return datetime.now(timezone.utc)

class Base(DeclarativeBase): pass

class User(Base):
    __tablename__='users'
    id: Mapped[int]=mapped_column(primary_key=True)
    email: Mapped[str]=mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str]=mapped_column(Text)
    role: Mapped[str]=mapped_column(String(30), default='commercial')
    is_active: Mapped[bool]=mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)

class Lead(Base):
    __tablename__='leads'
    id: Mapped[int]=mapped_column(primary_key=True)
    assigned_user_id: Mapped[int]=mapped_column(ForeignKey('users.id'), index=True)
    name: Mapped[str]=mapped_column(String(255))
    address: Mapped[Optional[str]]=mapped_column(Text, nullable=True)
    postal_code: Mapped[str]=mapped_column(String(10), index=True)
    business_type: Mapped[str]=mapped_column(String(100), index=True)
    business_subtype: Mapped[Optional[str]]=mapped_column(String(150), nullable=True)
    owner_name: Mapped[Optional[str]]=mapped_column(String(150), nullable=True)
    phone: Mapped[Optional[str]]=mapped_column(String(60), nullable=True)
    status: Mapped[str]=mapped_column(String(30), index=True, default='pending')
    next_action: Mapped[Optional[str]]=mapped_column(Text, nullable=True)
    follow_up_at: Mapped[Optional[datetime]]=mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow, index=True)
Index('ix_leads_user_updated', Lead.assigned_user_id, Lead.updated_at.desc(), Lead.id.desc())
Index('ix_leads_user_postal', Lead.assigned_user_id, Lead.postal_code)
Index('ix_leads_user_status', Lead.assigned_user_id, Lead.status)

class Activity(Base):
    __tablename__='activities'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'), index=True)
    actor_user_id: Mapped[int]=mapped_column(ForeignKey('users.id'), index=True)
    activity_type: Mapped[str]=mapped_column(String(40), index=True)
    notes: Mapped[Optional[str]]=mapped_column(Text, nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow, index=True)
Index('ix_activities_user_created', Activity.actor_user_id, Activity.created_at.desc())

class Sale(Base):
    __tablename__='sales'
    id: Mapped[int]=mapped_column(primary_key=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('leads.id'), index=True)
    actor_user_id: Mapped[int]=mapped_column(ForeignKey('users.id'), index=True)
    quantity: Mapped[int]=mapped_column(Integer)
    unit_price: Mapped[Decimal]=mapped_column(Numeric(10,2))
    total: Mapped[Decimal]=mapped_column(Numeric(12,2))
    payment_method: Mapped[str]=mapped_column(String(30))
    delivered: Mapped[bool]=mapped_column(Boolean, default=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow, index=True)
Index('ix_sales_user_created', Sale.actor_user_id, Sale.created_at.desc())

class AuditLog(Base):
    __tablename__='audit_logs'
    id: Mapped[int]=mapped_column(primary_key=True)
    actor_user_id: Mapped[int]=mapped_column(ForeignKey('users.id'), index=True)
    lead_id: Mapped[Optional[int]]=mapped_column(ForeignKey('leads.id'), nullable=True, index=True)
    event_type: Mapped[str]=mapped_column(String(60), index=True)
    payload: Mapped[str]=mapped_column(Text, default='{}')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow, index=True)

class IdempotencyKey(Base):
    __tablename__='idempotency_keys'
    key: Mapped[str]=mapped_column(String(120), primary_key=True)
    actor_user_id: Mapped[int]=mapped_column(ForeignKey('users.id'), index=True)
    response_json: Mapped[str]=mapped_column(Text)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True), default=utcnow)
