import os, json, base64, hmac, hashlib, secrets
from datetime import timedelta
from typing import Optional
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from .db import SessionLocal, User, utcnow

APP_ENV=os.getenv('APP_ENV','development')
SECRET_KEY=os.getenv('SECRET_KEY','')
TOKEN_HOURS=int(os.getenv('TOKEN_HOURS','168'))
if APP_ENV=='production' and len(SECRET_KEY)<32:
    raise RuntimeError('SECRET_KEY debe tener al menos 32 caracteres en producción')

def hash_password(password:str)->str:
    salt=secrets.token_bytes(16); dk=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,250_000)
    return f"pbkdf2_sha256$250000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(dk).decode()}"

def verify_password(password:str,stored:str)->bool:
    try:
        _,rounds,salt_b64,hash_b64=stored.split('$',3)
        salt=base64.urlsafe_b64decode(salt_b64.encode()); expected=base64.urlsafe_b64decode(hash_b64.encode())
        got=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,int(rounds)); return hmac.compare_digest(got,expected)
    except Exception: return False

def _b64(b:bytes)->str: return base64.urlsafe_b64encode(b).decode().rstrip('=')
def _b64d(s:str)->bytes: return base64.urlsafe_b64decode((s+'='*(-len(s)%4)).encode())
def sign_token(user_id:int)->str:
    payload={'sub':user_id,'exp':int((utcnow()+timedelta(hours=TOKEN_HOURS)).timestamp())}
    body=_b64(json.dumps(payload,separators=(',',':')).encode()); sig=_b64(hmac.new(SECRET_KEY.encode(),body.encode(),hashlib.sha256).digest())
    return body+'.'+sig

def verify_token(token:str)->int:
    try:
        body,sig=token.split('.',1); expected=_b64(hmac.new(SECRET_KEY.encode(),body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(sig,expected): raise ValueError()
        payload=json.loads(_b64d(body))
        if payload['exp']<int(utcnow().timestamp()): raise ValueError()
        return int(payload['sub'])
    except Exception: raise HTTPException(401,'Sesión no válida')

def get_db():
    db=SessionLocal()
    try: yield db
    finally: db.close()

def current_user(authorization:Optional[str]=Header(None),db:Session=Depends(get_db))->User:
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Inicia sesión')
    user=db.get(User,verify_token(authorization[7:]))
    if not user or not user.is_active: raise HTTPException(401,'Usuario no válido')
    return user
