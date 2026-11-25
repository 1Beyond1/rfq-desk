"""Local accounts and revocable, server-side sessions. No default credentials."""
from contextvars import ContextVar
from datetime import date
from pathlib import Path
import hashlib
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

USER = ContextVar('rfq_account', default=None)
COOKIE = 'rfq_session'
SESSION_TTL = 8 * 3600
IDLE_TTL = 30 * 60
_ACTIVE_ACCOUNTS = None


def demo_ai_calls():
    """AI operations per judge space; the daily model ledger still caps the whole site."""
    return max(1, min(int(os.getenv('RFQ_DEMO_AI_CALLS', '20')), 100))


def demo_ip_limit():
    """Max demo spaces created per IP within a 15-minute window."""
    return max(1, min(int(os.getenv('RFQ_DEMO_IP_LIMIT', '6')), 100))


def demo_daily_calls():
    """Site-wide daily AI call cap reserved for demo spaces so they cannot starve formal users."""
    return max(1, min(int(os.getenv('RFQ_DEMO_DAILY_CALLS', '60')), 5000))


def reserve_current_demo_call():
    """Charge one actual model/auxiliary request against the current demo user and daily demo cap."""
    if _ACTIVE_ACCOUNTS is not None:
        _ACTIVE_ACCOUNTS.reserve_demo_call()


HASH_SLOTS = threading.BoundedSemaphore(6)


def enabled():
    return os.getenv('RFQ_AUTH_REQUIRED') == '1'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    if not 15 <= len(password) <= 128:
        raise HTTPException(422, '密码需为15–128个字符，可使用长短语')
    salt = salt or secrets.token_hex(16)
    if not HASH_SLOTS.acquire(blocking=False):
        raise HTTPException(429, '登录请求较多，请稍后重试')
    try:
        value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=2**17,
                               r=8, p=1, dklen=32, maxmem=192*1024*1024)
        return 'scrypt$' + salt + '$' + value.hex()
    finally:
        HASH_SLOTS.release()


def verify_password(password, stored):
    # Unknown accounts perform the same expensive operation without revealing existence.
    stored = stored or 'scrypt$' + '00'*16 + '$' + '00'*32
    try:
        _, salt, _ = stored.split('$')
        return secrets.compare_digest(password_hash(password, salt), stored)
    except (ValueError, HTTPException) as e:
        if isinstance(e, HTTPException) and e.status_code == 429:
            raise
        return False


def actor_label(user):
    """Who a decision is recorded under. A judge's visitor account is random and session-only, so a short tag is enough to tell visitors apart."""
    if user.get('role') == 'demo':
        return f"{user['name']}（访客 {user['username'][5:13]}）"
    return f"{user['name']} ({user['username']})"


def public_user(row):
    return {k: row[k] for k in ('id', 'username', 'name', 'role', 'active', 'must_change', 'created')}


class Accounts:
    def __init__(self, connection, upload_root=None):
        global _ACTIVE_ACCOUNTS
        self.connection = connection
        self.upload_root = upload_root
        _ACTIVE_ACCOUNTS = self

    def schema(self, c):
        c.row_factory = sqlite3.Row
        c.execute('CREATE TABLE IF NOT EXISTS auth_users (id TEXT PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE NOT NULL, name TEXT NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL, must_change INTEGER NOT NULL, created INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS auth_sessions (token TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, expires INTEGER NOT NULL, seen INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS auth_attempts (bucket TEXT PRIMARY KEY, since INTEGER NOT NULL, count INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS auth_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS auth_demo_calls (user_id TEXT PRIMARY KEY, count INTEGER NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS auth_demo_daily (day TEXT PRIMARY KEY, count INTEGER NOT NULL)')

    def audit(self, c, actor, action, subject):
        c.execute('INSERT INTO auth_events(at,actor,action,subject) VALUES(?,?,?,?)', (int(time.time()), actor, action, subject))

    def create(self, username, name, password, role='user', actor='local-console', must_change=True):
        username = username.strip().lower()
        if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{2,39}', username):
            raise HTTPException(422, '账号需为3–40位小写字母、数字、点、短横线或下划线')
        if not name.strip() or len(name.strip()) > 60 or role not in ('user', 'admin'):
            raise HTTPException(422, '请填写60字以内姓名，并选择有效角色')
        hashed = password_hash(password)
        user_id = secrets.token_hex(16)
        try:
            with self.connection() as c:
                self.schema(c)
                c.execute('INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?)',
                          (user_id, username, name.strip(), hashed, role, 1, int(must_change), int(time.time())))
                self.audit(c, actor, 'account_create', user_id)
                return public_user(c.execute('SELECT * FROM auth_users WHERE id=?', (user_id,)).fetchone())
        except sqlite3.IntegrityError:
            raise HTTPException(409, '账号已存在')

    def session(self, raw, touch=True):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', raw or ''):
            return None
        now = int(time.time())
        with self.connection() as c:
            self.schema(c)
            row = c.execute('SELECT u.*, s.csrf, s.expires, s.seen FROM auth_sessions s JOIN auth_users u ON u.id=s.user_id WHERE s.token=?', (digest(raw),)).fetchone()
            if not row or not row['active'] or row['expires'] <= now or row['seen'] <= now-IDLE_TTL:
                c.execute('DELETE FROM auth_sessions WHERE token=?', (digest(raw),))
                return None
            if touch: c.execute('UPDATE auth_sessions SET seen=? WHERE token=?', (now, digest(raw)))
            return {**public_user(row), 'csrf': row['csrf']}

    def authenticate(self, username, password, ip):
        username = username.strip().lower()
        now = int(time.time())
        buckets = [(digest('login:'+username), 10), (digest('ip:'+ip), 120)]
        with self.connection() as c:
            self.schema(c)
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM auth_attempts WHERE since<?', (now-900,))
            c.execute('DELETE FROM auth_sessions WHERE expires<? OR seen<?', (now, now-IDLE_TTL))
            for key, limit in buckets:
                row = c.execute('SELECT count FROM auth_attempts WHERE bucket=?', (key,)).fetchone()
                if row and row[0] >= limit:
                    raise HTTPException(429, '尝试次数过多，请15分钟后重试')
            for key, _ in buckets:
                c.execute('INSERT INTO auth_attempts VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1', (key, now))
            row = c.execute('SELECT * FROM auth_users WHERE username=?', (username,)).fetchone()
        if not verify_password(password, row['password'] if row else None) or not row or not row['active']:
            raise HTTPException(401, '账号或密码不正确，或账号已停用')
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connection() as c:
            self.schema(c)
            # Recheck state after the expensive hash, in the same transaction as session creation.
            c.execute('BEGIN IMMEDIATE')
            latest = c.execute('SELECT * FROM auth_users WHERE id=?', (row['id'],)).fetchone()
            if not latest['active'] or latest['password'] != row['password']:
                raise HTTPException(401, '账号或密码不正确，或账号已停用')
            c.execute('DELETE FROM auth_attempts WHERE bucket=?', (buckets[0][0],))
            c.execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?)', (digest(raw), row['id'], csrf, now+SESSION_TTL, now))
            self.audit(c, row['id'], 'login', row['id'])
        return raw, {**public_user(row), 'csrf': csrf}

    def revoke(self, raw):
        with self.connection() as c:
            self.schema(c)
            c.execute('DELETE FROM auth_sessions WHERE token=?', (digest(raw),))

    def cleanup_expired_demos(self, now=None):
        """Reclaim expired/logged-out demo accounts, their DB rows, and uploaded case folders."""
        now = int(time.time()) if now is None else int(now)
        removed_cases = []
        with self.connection() as c:
            self.schema(c); c.execute('BEGIN IMMEDIATE')
            expired = [
                r[0] for r in c.execute(
                    "SELECT u.id FROM auth_users u WHERE u.role='demo' AND NOT EXISTS ("
                    "SELECT 1 FROM auth_sessions s WHERE s.user_id=u.id AND s.expires>? AND s.seen>?)",
                    (now, now - IDLE_TTL),
                ).fetchall()
            ]
            if not expired:
                return 0
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            for uid in expired:
                visitor = 'user:' + uid
                case_ids = [r[0] for r in c.execute('SELECT case_id FROM case_owners WHERE visitor=?', (visitor,)).fetchall()] if 'case_owners' in tables else []
                for cid in case_ids:
                    if 'cases' in tables: c.execute('DELETE FROM cases WHERE id=?', (cid,))
                    if 'case_owners' in tables: c.execute('DELETE FROM case_owners WHERE case_id=?', (cid,))
                    if 'agent_turns' in tables: c.execute('DELETE FROM agent_turns WHERE case_id=?', (cid,))
                    if 'case_snapshots' in tables: c.execute('DELETE FROM case_snapshots WHERE case_id=?', (cid,))
                    removed_cases.append(cid)
                if 'inbox_messages' in tables: c.execute('DELETE FROM inbox_messages WHERE owner=?', (visitor,))
                if 'agent_home_turns' in tables: c.execute('DELETE FROM agent_home_turns WHERE owner=?', (visitor,))
                c.execute('DELETE FROM auth_sessions WHERE user_id=?', (uid,))
                c.execute('DELETE FROM auth_demo_calls WHERE user_id=?', (uid,))
                c.execute('DELETE FROM auth_users WHERE id=?', (uid,))
        root = self.upload_root() if callable(self.upload_root) else self.upload_root
        if root is not None:
            upload_base = Path(root).resolve()
            for cid in removed_cases:
                if isinstance(cid, str) and cid and Path(cid).name == cid and cid not in ('.', '..'):
                    raw_target = upload_base / cid
                    if raw_target.is_symlink():
                        continue
                    target = raw_target.resolve()
                    if target.parent == upload_base and target.exists():
                        shutil.rmtree(target, ignore_errors=True)
        return len(expired)

    def demo(self, ip):
        now=int(time.time());user_id=secrets.token_hex(16)
        raw,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
        self.cleanup_expired_demos(now=now)
        with self.connection() as c:
            self.schema(c);c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM auth_attempts WHERE since<?',(now-900,))
            bucket=digest('demo:'+ip)
            attempt=c.execute('SELECT count FROM auth_attempts WHERE bucket=?',(bucket,)).fetchone()
            if attempt and attempt[0]>=demo_ip_limit():raise HTTPException(429,'体验创建较频繁，请稍后再试或联系作者')
            recent_users=c.execute("SELECT COUNT(*) FROM auth_users WHERE role='demo' AND created>?",(now-3600,)).fetchone()[0]
            recent_events=c.execute("SELECT COUNT(*) FROM auth_events WHERE action='demo_start' AND at>?",(now-3600,)).fetchone()[0]
            if max(recent_users, recent_events)>=100:
                raise HTTPException(429,'当前体验人数较多，请稍后再试')
            c.execute('INSERT INTO auth_attempts VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1',(bucket,now))
            # An unusable password: this account can only be reached through its own random session.
            c.execute('INSERT INTO auth_users VALUES(?,?,?,?,?,?,?,?)',(user_id,'demo.'+user_id,'访客体验','!session-only','demo',1,0,now))
            c.execute('INSERT INTO auth_sessions VALUES(?,?,?,?,?)',(digest(raw),user_id,csrf,now+3600,now))
            self.audit(c,user_id,'demo_start',user_id)
            return raw,{**public_user(c.execute('SELECT * FROM auth_users WHERE id=?',(user_id,)).fetchone()),'csrf':csrf}

    def check_demo_call(self):
        user=USER.get()
        if not user or user['role']!='demo':return
        today=date.today().isoformat()
        with self.connection() as c:
            self.schema(c)
            row=c.execute('SELECT count FROM auth_demo_calls WHERE user_id=?',(user['id'],)).fetchone()
            limit=demo_ai_calls()
            if row and row[0]>=limit:raise HTTPException(429,f'本体验空间的{limit}次AI操作已用完；核对、核价、批准和导出仍可继续')
            daily=c.execute('SELECT count FROM auth_demo_daily WHERE day=?',(today,)).fetchone()
            daily_limit=demo_daily_calls()
            if daily and daily[0]>=daily_limit:raise HTTPException(429,f'今日体验AI总额度（{daily_limit}次）已用完；核对、核价、批准和导出仍可继续')

    def reserve_demo_call(self):
        user=USER.get()
        if not user or user['role']!='demo':return
        today=date.today().isoformat()
        with self.connection() as c:
            self.schema(c);c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT count FROM auth_demo_calls WHERE user_id=?',(user['id'],)).fetchone()
            limit=demo_ai_calls()
            if row and row[0]>=limit:raise HTTPException(429,f'本体验空间的{limit}次AI操作已用完；核对、核价、批准和导出仍可继续')
            daily=c.execute('SELECT count FROM auth_demo_daily WHERE day=?',(today,)).fetchone()
            daily_limit=demo_daily_calls()
            if daily and daily[0]>=daily_limit:raise HTTPException(429,f'今日体验AI总额度（{daily_limit}次）已用完；核对、核价、批准和导出仍可继续')
            c.execute('INSERT INTO auth_demo_calls VALUES(?,1) ON CONFLICT(user_id) DO UPDATE SET count=count+1',(user['id'],))
            c.execute('INSERT INTO auth_demo_daily VALUES(?,1) ON CONFLICT(day) DO UPDATE SET count=count+1',(today,))

    def change_password(self, user, old, new):
        with self.connection() as c:
            self.schema(c)
            c.execute('BEGIN IMMEDIATE')
            bucket=digest('password-change:'+user['id'])
            now=int(time.time())
            c.execute('DELETE FROM auth_attempts WHERE since<?', (now-900,))
            attempt=c.execute('SELECT count FROM auth_attempts WHERE bucket=?', (bucket,)).fetchone()
            if attempt and attempt[0]>=10: raise HTTPException(429, '尝试次数过多，请15分钟后重试')
            c.execute('INSERT INTO auth_attempts VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1', (bucket,now))
            row = c.execute('SELECT password FROM auth_users WHERE id=?', (user['id'],)).fetchone()
        if not row or not verify_password(old, row[0]):
            raise HTTPException(422, '原密码不正确')
        if secrets.compare_digest(old.encode(), new.encode()):
            raise HTTPException(422, '新密码需与原密码不同')
        hashed = password_hash(new)
        with self.connection() as c:
            self.schema(c)
            c.execute('BEGIN IMMEDIATE')
            changed = c.execute('UPDATE auth_users SET password=?,must_change=0 WHERE id=? AND password=? AND active=1', (hashed, user['id'], row[0]))
            if not changed.rowcount:
                raise HTTPException(409, '账号状态已变化，请重新登录')
            c.execute('DELETE FROM auth_sessions WHERE user_id=?', (user['id'],))
            self.audit(c, user['id'], 'password_change', user['id'])


def check_origin(request):
    origin = request.headers.get('origin')
    expected = os.getenv('RFQ_PUBLIC_ORIGIN', '').rstrip('/') or str(request.base_url).rstrip('/')
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != expected):
        raise HTTPException(403, '请求来源不受信任，请从本站打开')


def secure_cookie(request):
    return os.getenv('RFQ_COOKIE_SECURE', '1') == '1' or request.url.scheme == 'https'


def current_user(admin=False):
    user = USER.get()
    if not enabled() or not user:
        raise HTTPException(401, '请先登录')
    if admin and user['role'] != 'admin':
        raise HTTPException(403, '仅管理员可以管理账号')
    return user


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=128)


class CreateUser(Login):
    name: str = Field(min_length=1, max_length=60)


class PasswordChange(BaseModel):
    old_password: str = Field(max_length=128)
    new_password: str = Field(min_length=15, max_length=128)


class AccountState(BaseModel):
    active: bool


def router(store):
    routes = APIRouter(prefix='/api')

    @routes.get('/auth/session')
    def session():
        if not enabled():
            return {'required': False, 'user': None}
        user = USER.get()
        return {'required': True, 'user': {k:v for k,v in user.items() if k != 'csrf'} if user else None, 'csrf': user['csrf'] if user else None}

    @routes.post('/auth/login')
    def login(body: Login, request: Request, response: Response):
        if not enabled():
            raise HTTPException(404, '本环境未开启账号登录')
        if request.headers.get('content-type', '').split(';')[0] != 'application/json':
            raise HTTPException(415, '请使用登录表单')
        check_origin(request)
        raw, user = store.authenticate(body.username, body.password, request.client.host if request.client else 'local')
        # Rotate even when logging into the same account; the old cookie is no longer valid.
        store.revoke(request.cookies.get(COOKIE, ''))
        response.set_cookie(COOKIE, raw, max_age=SESSION_TTL, httponly=True, secure=secure_cookie(request), samesite='strict', path='/')
        return {'required': True, 'user': {k:v for k,v in user.items() if k != 'csrf'}, 'csrf': user['csrf']}

    @routes.post('/auth/logout')
    def logout(request: Request, response: Response):
        current_user()
        store.revoke(request.cookies.get(COOKIE, ''))
        response.delete_cookie(COOKIE, path='/', secure=secure_cookie(request), httponly=True, samesite='strict')
        return {'ok': True}

    @routes.post('/auth/demo')
    def demo(request: Request, response: Response):
        if not enabled():raise HTTPException(404,'本环境未开启访客体验')
        check_origin(request)
        if request.headers.get('content-type','').split(';')[0]!='application/json':raise HTTPException(415,'请从登录页进入访客体验')
        existing=USER.get()
        if existing:
            if existing['role']!='demo':raise HTTPException(409,'请先退出当前账号，再进入独立体验空间')
            raw,user=request.cookies.get(COOKIE),existing
        else:raw,user=store.demo(request.client.host if request.client else 'local')
        response.set_cookie(COOKIE,raw,max_age=3600,httponly=True,secure=secure_cookie(request),samesite='strict',path='/')
        return {'required':True,'user':{k:v for k,v in user.items() if k!='csrf'},'csrf':user['csrf']}

    @routes.post('/auth/password')
    def change(body: PasswordChange, request: Request, response: Response):
        if current_user()['role']=='demo':raise HTTPException(403,'体验账号不设置密码，请使用正式账号登录')
        store.change_password(current_user(), body.old_password, body.new_password)
        response.delete_cookie(COOKIE, path='/', secure=secure_cookie(request), httponly=True, samesite='strict')
        return {'ok': True}

    @routes.get('/admin/users')
    def users():
        current_user(admin=True)
        with store.connection() as c:
            store.schema(c)
            return [public_user(r) for r in c.execute("SELECT * FROM auth_users WHERE role IN ('user','admin') ORDER BY created,username")]

    @routes.post('/admin/users')
    def create(body: CreateUser):
        actor = current_user(admin=True)
        return store.create(body.username, body.name, body.password, actor=actor['id'])

    @routes.patch('/admin/users/{user_id}')
    def state(user_id: str, body: AccountState):
        actor = current_user(admin=True)
        if actor['id'] == user_id:
            raise HTTPException(422, '不能停用当前登录账号')
        with store.connection() as c:
            store.schema(c)
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM auth_users WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise HTTPException(404, '账号不存在')
            if row['role'] == 'admin':
                raise HTTPException(422, '管理员账号请由本机维护命令管理')
            c.execute('UPDATE auth_users SET active=? WHERE id=?', (int(body.active), user_id))
            if not body.active:
                c.execute('DELETE FROM auth_sessions WHERE user_id=?', (user_id,))
            store.audit(c, actor['id'], 'account_enable' if body.active else 'account_disable', user_id)
        return {'ok': True}

    @routes.get('/admin/audit')
    def audit():
        current_user(admin=True)
        with store.connection() as c:
            store.schema(c)
            return [dict(r) for r in c.execute('SELECT e.at,e.action,COALESCE(a.username,e.actor) actor,COALESCE(s.username,e.subject) subject FROM auth_events e LEFT JOIN auth_users a ON a.id=e.actor LEFT JOIN auth_users s ON s.id=e.subject ORDER BY e.seq DESC LIMIT 100')]

    return routes
