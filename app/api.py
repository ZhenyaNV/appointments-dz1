from datetime import datetime, timedelta
from typing import Literal
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field, field_validator
from app.db import connection
from app.auth import require_user, login, token_hash
from app import service

router=APIRouter(prefix='/api')

class Credentials(BaseModel):
    username: str=Field(min_length=1,max_length=80)
    password: str=Field(min_length=1,max_length=200)

class Booking(BaseModel):
    slot_id: int=Field(gt=0)
    service_id: int=Field(gt=0)
    client_name: str=Field(min_length=1,max_length=120)
    start_at: datetime | None=None

    @field_validator('client_name')
    @classmethod
    def nonempty(cls,value):
        if not value.strip(): raise ValueError('Укажите имя клиента')
        return value.strip()

    @field_validator('start_at')
    @classmethod
    def aware(cls,value):
        if value is not None and value.tzinfo is None: raise ValueError('Укажите часовой пояс')
        return value


def authorized_db(request: Request):
    with connection() as db:
        request.state.user=require_user(db,request)
        yield db

@router.post('/login')
def sign_in(data: Credentials,response: Response):
    with connection() as db: token,user=login(db,data.username,data.password)
    response.set_cookie('session',token,httponly=True,samesite='strict',max_age=28800)
    return user

@router.post('/logout')
def sign_out(request: Request,response: Response,db=Depends(authorized_db)):
    db.execute('DELETE FROM sessions WHERE token_hash=%s',(token_hash(request.cookies['session']),))
    response.delete_cookie('session')
    return {'ok':True}

@router.get('/me')
def me(request: Request,db=Depends(authorized_db)):
    return request.state.user

@router.get('/services')
def services(db=Depends(authorized_db)):
    return {'items':db.execute('SELECT * FROM services ORDER BY id').fetchall()}

@router.get('/specialists')
def specialists(db=Depends(authorized_db)):
    return {'items':db.execute('SELECT * FROM specialists ORDER BY id').fetchall()}

@router.get('/appointments')
def appointments(page: int=Query(1,ge=1,le=100000),size: int=Query(20,ge=1,le=100),
                 status: Literal['active','cancelled'] | None=None,specialist_id: int | None=Query(None,gt=0),
                 from_at: datetime=service.DEFAULT_FROM,to_at: datetime=service.DEFAULT_TO,db=Depends(authorized_db)):
    return service.list_appointments(db,page,size,status,specialist_id,from_at,to_at)

@router.get('/appointments/{aid}')
def appointment(aid: int,db=Depends(authorized_db)):
    return service.card(db,aid)

@router.post('/appointments',status_code=201)
def create(data: Booking,db=Depends(authorized_db)):
    return service.book(db,data)

@router.post('/appointments/{aid}/cancel')
def cancel(aid: int,db=Depends(authorized_db)):
    return service.cancel(db,aid)

@router.get('/slots')
def slots(service_id: int=Query(...,gt=0),specialist_id: int | None=Query(None,gt=0),
          from_at: datetime=service.DEFAULT_FROM,to_at: datetime=service.DEFAULT_FROM+timedelta(days=7),
          page: int=Query(1,ge=1,le=100000),size: int=Query(20,ge=1,le=100),db=Depends(authorized_db)):
    return service.free_slots(db,service_id,specialist_id,from_at,to_at,page,size)

@router.get('/summary')
def summary(from_at: datetime=service.DEFAULT_FROM,to_at: datetime=service.DEFAULT_TO,db=Depends(authorized_db)):
    return service.summary(db,from_at,to_at)
