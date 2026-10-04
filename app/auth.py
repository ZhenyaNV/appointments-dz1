import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException


def hash_password(password: str) -> str:
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 120000).hex()
    return f'{salt}:{digest}'


def verify_password(password, stored):
    salt, expected=stored.split(':')
    actual=hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 120000).hex()
    return hmac.compare_digest(expected, actual)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def require_user(db, request):
    token=request.cookies.get('session','')
    user=db.execute('SELECT u.id,u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=%s AND s.expires_at>now()', (token_hash(token),)).fetchone()
    if not user: raise HTTPException(401, 'Войдите в систему')
    return user


def login(db, username, password):
    user=db.execute('SELECT * FROM users WHERE username=%s',(username,)).fetchone()
    if not user or not verify_password(password,user['password_hash']):
        raise HTTPException(401,'Неверный логин или пароль')
    token=secrets.token_urlsafe(32)
    db.execute('INSERT INTO sessions(token_hash,user_id,expires_at) VALUES (%s,%s,%s)',
               (token_hash(token),user['id'],datetime.now(timezone.utc)+timedelta(hours=8)))
    return token, {'id':user['id'],'username':user['username']}
