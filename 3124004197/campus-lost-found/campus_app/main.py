import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from zoneinfo import ZoneInfo

from .db import Database
from .version import backend_version as get_backend_version
from .security import hash_password, verify_password, token_hash
from . import ai
from .matching import score_candidates, validate_ai_matches

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / '.env', override=False)
CAMPUS_TIMEZONE = ZoneInfo(os.getenv('APP_TIMEZONE', 'Asia/Shanghai'))
CATEGORIES = ['证件卡片', '数码设备', '钥匙', '衣物配饰', '文具书籍', '其他']


def now():
    return datetime.now(timezone.utc).isoformat()


def public_item(row):
    return {k: row[k] for k in ('id', 'owner_id', 'kind', 'title', 'category', 'description', 'location',
                              'occurred_on', 'photo_url', 'status', 'is_demo', 'created_at', 'nickname')}


class Account(BaseModel):
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=8, max_length=128)
    nickname: str = Field(min_length=1, max_length=32)
    contact: str = Field(min_length=2, max_length=100)

    @field_validator('username')
    @classmethod
    def username_valid(cls, value):
        if not re.fullmatch(r'[\w-]{3,24}', value):
            raise ValueError('账号只能包含字母、数字、汉字、下划线或短横线')
        if value.casefold() in ('demo_lost', 'demo_found'):
            raise ValueError('该账号保留用于演示')
        return value.casefold()

    @field_validator('nickname', 'contact', mode='before')
    @classmethod
    def nonblank(cls, value):
        if not isinstance(value, str): return value
        if not value.strip():
            raise ValueError('不能只填写空格')
        return value.strip()


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=24)
    password: str = Field(min_length=1, max_length=128)


class ProfileInput(BaseModel):
    nickname: str = Field(min_length=1, max_length=32)
    contact: str = Field(min_length=2, max_length=100)

    @field_validator('nickname', 'contact', mode='before')
    @classmethod
    def strip_values(cls, value):
        return value.strip() if isinstance(value, str) else value


class PasswordInput(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class ItemEdit(BaseModel):
    title: str = Field(min_length=2, max_length=80)
    category: str
    description: str = Field(min_length=5, max_length=2000)
    location: str = Field(min_length=2, max_length=100)
    occurred_on: date
    verification_hint: str = Field(default='', max_length=500)

    @field_validator('category')
    @classmethod
    def category_valid(cls, value):
        if value not in CATEGORIES:
            raise ValueError('请选择有效类别')
        return value

    @field_validator('title', 'description', 'location', mode='before')
    @classmethod
    def strip_required(cls, value):
        if not isinstance(value, str): return value
        if not value.strip():
            raise ValueError('必填信息不能为空')
        return value.strip()

    @field_validator('occurred_on')
    @classmethod
    def date_valid(cls, value):
        if value > datetime.now(CAMPUS_TIMEZONE).date():
            raise ValueError('物品日期不能晚于今天')
        return value


class ClaimInput(BaseModel):
    proof: str = Field(min_length=8, max_length=2000)

    @field_validator('proof')
    @classmethod
    def proof_valid(cls, value):
        if len(value.strip()) < 8:
            raise ValueError('请至少填写八个字的核验说明')
        return value.strip()


class Decision(BaseModel):
    decision: Literal['accept', 'reject']
    note: str = Field(default='', max_length=500)
    expected_updated_at: str | None = Field(default=None, max_length=60)


class Question(BaseModel):
    message: str = Field(min_length=1, max_length=2000)

    @field_validator('message')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('请输入问题')
        return value.strip()


def create_app(data_dir=None, demo=None):
    database = Database(data_dir or os.getenv('DATA_DIR', str(ROOT / 'data')))
    uploads = database.directory / 'uploads'
    uploads.mkdir(exist_ok=True)

    demo_mode = demo if demo is not None else os.getenv('ENABLE_DEMO') == '1'

    @asynccontextmanager
    async def lifespan(app):
        database.initialize()
        if demo_mode:
            from .seed import seed_demo
            seed_demo(database)
        yield

    backend_version = get_backend_version()
    config_revision = (ROOT / '.env').stat().st_mtime_ns if (ROOT / '.env').exists() else 0
    app = FastAPI(title='校园失物找回助手', lifespan=lifespan)
    app.state.db = database
    app.state.ai_slots = asyncio.Semaphore(2)
    app.state.chat_locks = {}
    app.state.login_failures = {}

    @app.middleware('http')
    async def headers_and_origin(request, call_next):
        origin = request.headers.get('origin')
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and origin:
            from urllib.parse import urlparse
            if urlparse(origin).netloc != request.headers.get('host'):
                return JSONResponse({'detail': '不允许跨站操作'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        return response

    def current_user(request: Request):
        token = request.cookies.get('campus_session')
        if not token:
            raise HTTPException(401, '请先登录')
        with database.connect() as conn:
            row = conn.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?',
                               (token_hash(token), time.time())).fetchone()
        if not row:
            raise HTTPException(401, '登录已失效，请重新登录')
        return dict(row)

    def optional_user(request):
        try:
            return current_user(request)
        except HTTPException:
            return None

    def owner_item(ident, owner):
        with database.connect() as conn:
            item = conn.execute('SELECT * FROM items WHERE id=? AND deleted=0', (ident,)).fetchone()
        if not item:
            raise HTTPException(404, '物品信息不存在')
        if item['owner_id'] != owner['id']:
            raise HTTPException(403, '只能管理自己发布的信息')
        return item

    def issue_session(user, response):
        token = secrets.token_urlsafe(32)
        with database.connect() as conn:
            conn.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            conn.execute('INSERT INTO sessions VALUES(?,?,?)', (token_hash(token), user['id'], time.time()+7*86400))
        response.set_cookie('campus_session', token, httponly=True, samesite='lax', secure=os.getenv('COOKIE_SECURE') == '1', max_age=7*86400)
        return {k: user[k] for k in ('id', 'username', 'nickname', 'contact')}

    @app.get('/api/health')
    async def health():
        version = hashlib.sha256((ROOT / 'public/app.js').read_bytes()).hexdigest()[:12]
        return {'application': 'campus-lost-found', 'frontend_version': version, 'backend_version': backend_version,
                'project_id': hashlib.sha256(str(ROOT).encode()).hexdigest()[:12], 'config_revision': config_revision,
                'data_id': hashlib.sha256(str(database.directory.resolve()).encode()).hexdigest()[:12], 'demo_enabled': demo_mode,
                'ai_configured': bool(os.getenv('DEEPSEEK_API_KEY'))}

    @app.get('/api/meta')
    async def meta():
        with database.connect() as conn:
            counts = dict(conn.execute("SELECT kind,COUNT(*) FROM items WHERE deleted=0 AND status='active' GROUP BY kind").fetchall())
            returned = conn.execute("SELECT COUNT(*) FROM items WHERE deleted=0 AND status='returned'").fetchone()[0]
        return {'categories': CATEGORIES, 'counts': {'lost': counts.get('lost', 0), 'found': counts.get('found', 0), 'returned': returned},
                'ai_configured': bool(os.getenv('DEEPSEEK_API_KEY'))}

    @app.post('/api/auth/register')
    async def register(body: Account, response: Response):
        try:
            encoded = await asyncio.to_thread(hash_password, body.password)
            with database.connect() as conn:
                cur = conn.execute('INSERT INTO users(username,nickname,password_hash,contact,created_at) VALUES(?,?,?,?,?)',
                                   (body.username, body.nickname, encoded, body.contact, now()))
                ident = cur.lastrowid
            return issue_session({'id': ident, **body.model_dump()}, response)
        except sqlite3.IntegrityError:
            raise HTTPException(409, '账号已被使用') from None

    @app.post('/api/auth/login')
    async def login(body: Login, request: Request, response: Response):
        address = request.client.host if request.client else 'local'
        failures = [t for t in app.state.login_failures.get(address, []) if time.time()-t < 300]
        if len(failures) >= 15:
            raise HTTPException(429, '登录尝试过多，请五分钟后重试')
        with database.connect() as conn:
            user = conn.execute('SELECT * FROM users WHERE username=?', (body.username.casefold(),)).fetchone()
        valid = await asyncio.to_thread(verify_password, body.password, user['password_hash'] if user else 'invalid')
        if not user or not valid:
            app.state.login_failures[address] = failures + [time.time()]
            raise HTTPException(401, '账号或密码不正确')
        app.state.login_failures.pop(address, None)
        return issue_session(dict(user), response)

    @app.get('/api/auth/me')
    async def me(user=Depends(current_user)):
        return {k: user[k] for k in ('id', 'username', 'nickname', 'contact')}

    @app.post('/api/auth/logout')
    async def logout(request: Request, response: Response):
        with database.connect() as conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(request.cookies.get('campus_session', '')),))
        response.delete_cookie('campus_session')
        return {'ok': True}

    @app.patch('/api/auth/profile')
    async def profile(body: ProfileInput, user=Depends(current_user)):
        if user['username'] in ('demo_lost','demo_found'):
            raise HTTPException(403,'演示账号资料固定，请注册自己的账号后修改')
        with database.connect() as conn:
            conn.execute('UPDATE users SET nickname=?,contact=? WHERE id=?', (body.nickname,body.contact,user['id']))
        return {'id':user['id'],'username':user['username'],'nickname':body.nickname,'contact':body.contact}

    @app.post('/api/auth/password')
    async def password(body: PasswordInput, request: Request, user=Depends(current_user)):
        if user['username'] in ('demo_lost','demo_found'):
            raise HTTPException(403,'演示账号密码固定，请注册自己的账号')
        if not await asyncio.to_thread(verify_password,body.current_password,user['password_hash']):
            raise HTTPException(400,'当前密码不正确')
        encoded=await asyncio.to_thread(hash_password,body.new_password)
        with database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            changed=conn.execute('UPDATE users SET password_hash=? WHERE id=? AND password_hash=?', (encoded,user['id'],user['password_hash']))
            if not changed.rowcount:raise HTTPException(409,'密码已发生变化，请重新登录')
            conn.execute('DELETE FROM sessions WHERE user_id=? AND token_hash<>?', (user['id'],token_hash(request.cookies.get('campus_session',''))))
        return {'ok':True}

    @app.get('/api/items')
    async def board(q: str = '', kind: str = '', category: str = '', status: str = 'active', page: int = 1,
                    date_from: date | None = None, date_to: date | None = None, include_demo: bool = True):
        clauses, params = ['i.deleted=0'], []
        if kind in ('lost', 'found'):
            clauses.append('i.kind=?'); params.append(kind)
        if category:
            clauses.append('i.category=?'); params.append(category)
        if status in ('active', 'returned'):
            clauses.append('i.status=?'); params.append(status)
        if not include_demo:
            clauses.append('i.is_demo=0')
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422,'起始日期不能晚于结束日期')
        if date_from:
            clauses.append('i.occurred_on>=?');params.append(date_from.isoformat())
        if date_to:
            clauses.append('i.occurred_on<=?');params.append(date_to.isoformat())
        if q.strip():
            word = q.strip()[:100].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            clauses.append("(i.title LIKE ? ESCAPE '\\' OR i.description LIKE ? ESCAPE '\\' OR i.location LIKE ? ESCAPE '\\')")
            params.extend(['%'+word+'%']*3)
        where = ' AND '.join(clauses)
        with database.connect() as conn:
            total = conn.execute('SELECT COUNT(*) FROM items i WHERE '+where, params).fetchone()[0]
            rows = conn.execute('SELECT i.*,u.nickname FROM items i JOIN users u ON u.id=i.owner_id WHERE '+where+' ORDER BY i.created_at DESC,i.id DESC LIMIT 24 OFFSET ?',
                                [*params, (max(1, page)-1)*24]).fetchall()
        return {'items': [public_item(row) for row in rows], 'total': total, 'page': max(1, page)}

    @app.get('/api/me/items')
    async def mine(user=Depends(current_user)):
        with database.connect() as conn:
            rows = conn.execute('SELECT i.*,u.nickname FROM items i JOIN users u ON u.id=i.owner_id WHERE i.owner_id=? AND i.deleted=0 ORDER BY i.id DESC', (user['id'],)).fetchall()
        return {'items': [public_item(row) for row in rows]}

    @app.get('/api/items/{ident}')
    async def detail(ident: int, request: Request):
        with database.connect() as conn:
            row = conn.execute('SELECT i.*,u.nickname FROM items i JOIN users u ON u.id=i.owner_id WHERE i.id=? AND i.deleted=0', (ident,)).fetchone()
        if not row:
            raise HTTPException(404, '物品信息不存在')
        data = public_item(row)
        user = optional_user(request)
        if user and user['id'] == row['owner_id']:
            data['verification_hint'] = row['verification_hint']
        return data

    async def store_photo(photo):
        if photo is None:return None,None
        try:
            raw=await photo.read(5*1024*1024+1)
        finally:
            await photo.close()
        if len(raw)>5*1024*1024:raise HTTPException(413,'照片不能超过 5 MiB')
        try:
            with Image.open(io.BytesIO(raw)) as original:
                if original.format not in ('JPEG','PNG','WEBP') or original.width*original.height>15_000_000:
                    raise ValueError
                image=ImageOps.exif_transpose(original)
                image.thumbnail((1600,1600))
                image=image.convert('RGB')
        except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):
            raise HTTPException(422,'请选择有效的 JPG、PNG 或 WebP 照片，像素不超过 1500 万') from None
        path=uploads/(secrets.token_hex(16)+'.jpg')
        try:
            image.save(path,'JPEG',quality=85)
        except OSError:
            path.unlink(missing_ok=True)
            raise HTTPException(507,'照片保存失败，请检查服务存储') from None
        finally:image.close()
        return '/uploads/'+path.name,path

    @app.post('/api/items')
    async def publish(kind: Literal['lost','found'] = Form(...), title: str = Form(...), category: str = Form(...),
                      description: str = Form(...), location: str = Form(...), occurred_on: str = Form(...),
                      verification_hint: str = Form(''), photo: UploadFile | None = File(None), user=Depends(current_user)):
        try:
            fields = ItemEdit(title=title, category=category, description=description, location=location, occurred_on=occurred_on, verification_hint=verification_hint)
        except ValueError:
            raise HTTPException(422, '请检查标题、描述、地点、类别和日期') from None
        photo_url, image_path = await store_photo(photo)
        try:
            with database.connect() as conn:
                stamp = now()
                cur = conn.execute('INSERT INTO items(owner_id,kind,title,category,description,location,occurred_on,verification_hint,photo_url,is_demo,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                                   (user['id'],kind,fields.title,fields.category,fields.description,fields.location,fields.occurred_on.isoformat(),fields.verification_hint,photo_url,int(user['username'] in ('demo_lost','demo_found')),stamp,stamp))
                ident = cur.lastrowid
        except Exception:
            if image_path: image_path.unlink(missing_ok=True)
            raise
        return {'id': ident}

    @app.patch('/api/items/{ident}')
    async def edit(ident: int, fields: ItemEdit, user=Depends(current_user)):
        item = owner_item(ident, user)
        if item['status'] != 'active':
            raise HTTPException(409, '已归还的记录不能修改')
        with database.connect() as conn:
            conn.execute('UPDATE items SET title=?,category=?,description=?,location=?,occurred_on=?,verification_hint=?,updated_at=? WHERE id=?',
                         (fields.title,fields.category,fields.description,fields.location,fields.occurred_on.isoformat(),fields.verification_hint,now(),ident))
        return {'ok': True}

    @app.put('/api/items/{ident}')
    async def edit_with_photo(ident: int,title: str=Form(...),category: str=Form(...),description: str=Form(...),
                              location: str=Form(...),occurred_on: str=Form(...),verification_hint: str=Form(''),
                              clear_photo: bool=Form(False),photo: UploadFile | None=File(None),user=Depends(current_user)):
        owner_item(ident,user)
        try:fields=ItemEdit(title=title,category=category,description=description,location=location,occurred_on=occurred_on,verification_hint=verification_hint)
        except ValueError:raise HTTPException(422,'请检查标题、描述、地点、类别和日期') from None
        photo_url,new_path=await store_photo(photo)
        old_url=None
        try:
            with database.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                item=conn.execute('SELECT * FROM items WHERE id=? AND owner_id=? AND deleted=0',(ident,user['id'])).fetchone()
                if not item:raise HTTPException(404,'物品信息不存在')
                if item['status']!='active':raise HTTPException(409,'已归还的记录不能修改')
                old_url=item['photo_url']
                final_url=photo_url if photo_url else (None if clear_photo else old_url)
                conn.execute('UPDATE items SET title=?,category=?,description=?,location=?,occurred_on=?,verification_hint=?,photo_url=?,updated_at=? WHERE id=?',
                             (fields.title,fields.category,fields.description,fields.location,fields.occurred_on.isoformat(),fields.verification_hint,final_url,now(),ident))
        except BaseException:
            if new_path:new_path.unlink(missing_ok=True)
            raise
        if old_url and old_url!=final_url:(uploads/Path(old_url).name).unlink(missing_ok=True)
        return {'ok':True}

    @app.post('/api/items/{ident}/close')
    async def close(ident: int, user=Depends(current_user)):
        owner_item(ident, user)
        with database.connect() as conn:
            conn.execute("UPDATE items SET status='returned',updated_at=? WHERE id=?", (now(),ident))
            conn.execute("UPDATE claims SET status='rejected',resolution='returned',note='该物品已找回或归还',updated_at=? WHERE item_id=? AND status='pending'", (now(),ident))
        return {'ok': True}

    @app.delete('/api/items/{ident}')
    async def remove(ident: int, user=Depends(current_user)):
        item = owner_item(ident, user)
        with database.connect() as conn:
            if conn.execute("SELECT 1 FROM claims WHERE item_id=? AND status='pending'", (ident,)).fetchone():
                raise HTTPException(409, '请先处理待核验请求')
            conn.execute('UPDATE items SET deleted=1 WHERE id=?', (ident,))
        if item['photo_url']:
            (uploads / Path(item['photo_url']).name).unlink(missing_ok=True)
        return {'ok': True}

    @app.post('/api/items/{ident}/claims')
    async def request_claim(ident: int, body: ClaimInput, user=Depends(current_user)):
        with database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            item = conn.execute('SELECT * FROM items WHERE id=? AND deleted=0', (ident,)).fetchone()
            if not item:
                raise HTTPException(404, '物品信息不存在')
            if item['owner_id'] == user['id']:
                raise HTTPException(400, '不能认领自己发布的物品')
            if bool(item['is_demo']) != (user['username'] in ('demo_lost','demo_found')):
                raise HTTPException(403,'演示账号仅可处理演示记录；真实账号请使用真实线索')
            if item['status'] != 'active':
                raise HTTPException(409, '该物品已找回或归还')
            previous=conn.execute('SELECT * FROM claims WHERE item_id=? AND claimant_id=?',(ident,user['id'])).fetchone()
            if previous:
                if previous['status']!='rejected':raise HTTPException(409,'你已提交过请求，请在“我的请求”查看进展')
                if previous['proof']==body.proof and previous['resolution']!='withdrawn':
                    raise HTTPException(409,'请补充或修改核验说明后再提交')
                conn.execute("UPDATE claims SET proof=?,status='pending',resolution='',note='',updated_at=? WHERE id=?",(body.proof,now(),previous['id']))
                claim_id=previous['id']
            else:
                cur=conn.execute('INSERT INTO claims(item_id,claimant_id,proof,created_at,updated_at) VALUES(?,?,?,?,?)',(ident,user['id'],body.proof,now(),now()))
                claim_id=cur.lastrowid
        return {'id':claim_id}

    @app.post('/api/claims/{ident}/withdraw')
    async def withdraw(ident: int,user=Depends(current_user)):
        with database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT * FROM claims WHERE id=?',(ident,)).fetchone()
            if not row:raise HTTPException(404,'请求不存在')
            if row['claimant_id']!=user['id']:raise HTTPException(403,'只能撤回本人请求')
            if row['status']!='pending':raise HTTPException(409,'只有待核验请求可以撤回')
            conn.execute("UPDATE claims SET status='rejected',resolution='withdrawn',note='申请者已撤回',updated_at=? WHERE id=?",(now(),ident))
        return {'ok':True}

    @app.get('/api/me/claims')
    async def my_claims(user=Depends(current_user)):
        with database.connect() as conn:
            rows = conn.execute('SELECT c.*,i.title,i.kind,i.owner_id,i.status item_status,o.nickname owner_name,o.contact owner_contact,u.nickname claimant_name,u.contact claimant_contact FROM claims c JOIN items i ON i.id=c.item_id JOIN users o ON o.id=i.owner_id JOIN users u ON u.id=c.claimant_id WHERE i.owner_id=? OR c.claimant_id=? ORDER BY c.updated_at DESC,c.id DESC', (user['id'],user['id'])).fetchall()
        results = []
        for row in rows:
            data = {k: row[k] for k in ('id','item_id','claimant_id','proof','status','note','created_at','title','kind','owner_id','owner_name','claimant_name','item_status','updated_at','resolution')}
            if row['status'] == 'accepted':
                data['contact'] = row['claimant_contact'] if row['owner_id'] == user['id'] else row['owner_contact']
            results.append(data)
        return {'claims': results}

    @app.post('/api/claims/{ident}/decision')
    async def decide(ident: int, body: Decision, user=Depends(current_user)):
        with database.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            claim = conn.execute('SELECT c.*,i.owner_id,i.status item_status FROM claims c JOIN items i ON i.id=c.item_id WHERE c.id=?', (ident,)).fetchone()
            if not claim:
                raise HTTPException(404, '请求不存在')
            if claim['owner_id'] != user['id']:
                raise HTTPException(403, '只有发布者能进行核验')
            if claim['status'] != 'pending' or claim['item_status'] != 'active':
                raise HTTPException(409, '请求已处理或物品已归还')
            if body.expected_updated_at is not None and body.expected_updated_at != claim['updated_at']:
                raise HTTPException(409,'请求内容已变化，请刷新后重新核验')
            status = 'accepted' if body.decision == 'accept' else 'rejected'
            conn.execute('UPDATE claims SET status=?,resolution=?,note=?,updated_at=? WHERE id=?', (status,status,body.note,now(),ident))
            if status == 'accepted':
                conn.execute("UPDATE items SET status='returned',updated_at=? WHERE id=?", (now(),claim['item_id']))
                conn.execute("UPDATE claims SET status='rejected',resolution='returned',note='该物品已归还',updated_at=? WHERE item_id=? AND id<>? AND status='pending'", (now(),claim['item_id'],ident))
        return {'ok': True}

    async def run_ai(function, *args):
        try:
            await asyncio.wait_for(app.state.ai_slots.acquire(), timeout=.1)
        except asyncio.TimeoutError:
            raise HTTPException(429, 'AI 正忙，请稍后重试') from None
        try:
            task = asyncio.create_task(asyncio.to_thread(function, *args))
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                try: await task
                except Exception: pass
                raise
        finally:
            app.state.ai_slots.release()

    @app.post('/api/items/{ident}/matches')
    async def matches(ident: int, user=Depends(current_user)):
        item = owner_item(ident, user)
        if item['status'] != 'active':
            raise HTTPException(409, '已找回的记录不再匹配')
        with database.connect() as conn:
            rows = conn.execute('SELECT i.*,u.nickname FROM items i JOIN users u ON u.id=i.owner_id WHERE i.deleted=0 AND i.status=\'active\' AND i.kind<>? AND i.owner_id<>? AND i.is_demo=? ORDER BY i.id DESC LIMIT 150', (item['kind'], user['id'], item['is_demo'])).fetchall()
        target = {k: item[k] for k in ('id','kind','title','category','description','location','occurred_on')}
        candidates = [public_item(row) for row in rows]
        rules = score_candidates(target,candidates)
        revisions = {row['id']: row['updated_at'] for row in rows}

        def fresh_results(results):
            with database.connect() as conn:
                current = conn.execute('SELECT status,deleted,updated_at FROM items WHERE id=?',(ident,)).fetchone()
                if not current or current['deleted'] or current['status']!='active' or current['updated_at']!=item['updated_at']:
                    raise HTTPException(409,'物品信息已变化，请刷新后重新匹配')
                ids = [match['item']['id'] for match in results]
                if not ids:return []
                placeholders = ','.join('?' for _ in ids)
                query = "SELECT i.*,u.nickname FROM items i JOIN users u ON u.id=i.owner_id WHERE i.deleted=0 AND i.status='active' AND i.id IN ("+placeholders+")"
                live = {row['id']: row for row in conn.execute(query,ids).fetchall()}

            output = []
            for match in results:
                row = live.get(match['item']['id'])
                if row and row['updated_at']==revisions.get(row['id']):
                    output.append({**match,'item':public_item(row)})
            return output
        if not candidates:
            return {'matches': [], 'method': 'rules', 'message': '暂无同一数据范围的相反类型线索。演示与真实记录不会混合匹配，可以稍后再试。'}
        shortlist = [entry['item'] for entry in rules[:12]]
        try:
            raw = await run_ai(ai.rank_matches, target, shortlist)
            ranked = validate_ai_matches(raw, shortlist)
            return {'matches': fresh_results(ranked), 'method':'deepseek','message':'AI 仅提供线索，归属需由发布者核验。'}
        except HTTPException as exc:
            if exc.status_code != 429: raise
            return {'matches': fresh_results(rules[:8]), 'method':'rules', 'message':'AI 正忙，先展示关键词线索。'}
        except (ai.AIError,ValueError) as exc:
            return {'matches': fresh_results(rules[:8]), 'method':'rules','message':str(exc) if isinstance(exc,ai.AIError) else 'AI 匹配格式无效，先展示关键词线索。'}

    @app.get('/api/items/{ident}/chat')
    async def history(ident:int,user=Depends(current_user)):
        with database.connect() as conn:
            if not conn.execute('SELECT 1 FROM items WHERE id=? AND deleted=0',(ident,)).fetchone():
                raise HTTPException(404,'物品信息不存在')
            rows=conn.execute('SELECT role,content FROM chat_messages WHERE user_id=? AND item_id=? ORDER BY id DESC LIMIT 40',(user['id'],ident)).fetchall()
        return {'messages':[dict(row) for row in reversed(rows)]}

    @app.post('/api/items/{ident}/chat')
    async def consult(ident:int,body:Question,user=Depends(current_user)):
        lock = app.state.chat_locks.setdefault((user['id'],ident), asyncio.Lock())
        if lock.locked(): raise HTTPException(409,'请等待上一条回答完成')
        try:
            async with lock:
                with database.connect() as conn:
                    row=conn.execute('SELECT i.*,u.nickname FROM items i JOIN users u ON u.id=i.owner_id WHERE i.id=? AND i.deleted=0',(ident,)).fetchone()
                    history_rows=conn.execute('SELECT role,content FROM chat_messages WHERE user_id=? AND item_id=? ORDER BY id DESC LIMIT 40',(user['id'],ident)).fetchall()
                if not row: raise HTTPException(404,'物品信息不存在')
                reply = await run_ai(ai.chat_reply,public_item(row),[dict(r) for r in reversed(history_rows)],body.message)
                with database.connect() as conn:
                    conn.executemany('INSERT INTO chat_messages(user_id,item_id,role,content,created_at) VALUES(?,?,?,?,?)',
                                     [(user['id'],ident,'user',body.message,now()),(user['id'],ident,'assistant',reply,now())])
            return {'reply':reply}
        except ai.AIError as exc:
            raise HTTPException(502,str(exc)) from None

    @app.delete('/api/items/{ident}/chat')
    async def reset_chat(ident: int,user=Depends(current_user)):
        lock=app.state.chat_locks.setdefault((user['id'],ident),asyncio.Lock())
        if lock.locked():raise HTTPException(409,'请等待当前回答完成后清空对话')
        async with lock:
            with database.connect() as conn:
                conn.execute('DELETE FROM chat_messages WHERE user_id=? AND item_id=?',(user['id'],ident))
        return {'ok':True}

    app.mount('/uploads',StaticFiles(directory=uploads),name='uploads')
    app.mount('/',StaticFiles(directory=ROOT/'public',html=True),name='public')
    return app


app = create_app()
