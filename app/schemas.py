from decimal import Decimal
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class LoginIn(BaseModel):
    email:str
    password:str

class LeadCreate(BaseModel):
    name:str=Field(min_length=1,max_length=255)
    address:str=''
    postal_code:str=Field(pattern=r'^\d{5}$')
    business_type:str=Field(min_length=1,max_length=100)
    business_subtype:str=Field(default='',max_length=150)
    owner_name:str=Field(default='',max_length=150)
    phone:str=Field(default='',max_length=60)
    status:str='pending'
    follow_up_at:Optional[datetime]=None
    sale_quantity:int=Field(default=1,ge=1,le=1000)
    sale_unit_price:Decimal=Field(default=Decimal('25.00'),gt=0,le=100000)
    sale_payment_method:str='cash'
    sale_delivered:bool=True

class LeadPatch(BaseModel):
    name:Optional[str]=Field(default=None,min_length=1,max_length=255)
    address:Optional[str]=None
    postal_code:Optional[str]=Field(default=None,pattern=r'^\d{5}$')
    business_type:Optional[str]=Field(default=None,min_length=1,max_length=100)
    business_subtype:Optional[str]=Field(default=None,max_length=150)
    owner_name:Optional[str]=Field(default=None,max_length=150)
    phone:Optional[str]=Field(default=None,max_length=60)
    status:Optional[str]=None
    next_action:Optional[str]=None
    follow_up_at:Optional[datetime]=None
    sale_quantity:Optional[int]=Field(default=None,ge=1,le=1000)
    sale_unit_price:Optional[Decimal]=Field(default=None,gt=0,le=100000)
    sale_payment_method:Optional[str]=None
    sale_delivered:Optional[bool]=None

class ActivityCreate(BaseModel):
    activity_type:str
    notes:str=''

class SaleCreate(BaseModel):
    lead_id:int
    quantity:int=Field(ge=1,le=1000)
    unit_price:Decimal=Field(gt=0,le=100000)
    payment_method:str='cash'
    delivered:bool=True

class SalePatch(BaseModel):
    quantity:Optional[int]=Field(default=None,ge=1,le=1000)
    unit_price:Optional[Decimal]=Field(default=None,gt=0,le=100000)
    payment_method:Optional[str]=None
    delivered:Optional[bool]=None
