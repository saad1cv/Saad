import streamlit as st
import streamlit.components.v1 as _c
import sqlite3, os, json, re, random, time, secrets
from pathlib import Path
from datetime import datetime, timedelta

try:
    from google.oauth2 import id_token
    from google.auth.transport import requests as g_req
    GOOGLE_OK = True
except ImportError:
    GOOGLE_OK = False

st.set_page_config(page_title="StreamLine", page_icon="💬", layout="wide",
                   initial_sidebar_state="collapsed")

_cfg = {}
if Path("config.json").exists():
    with open("config.json") as f: _cfg = json.load(f)
GID  = _cfg.get("GOOGLE_CLIENT_ID",  os.getenv("GOOGLE_CLIENT_ID",""))
GSEC = _cfg.get("GOOGLE_CLIENT_SECRET", os.getenv("GOOGLE_CLIENT_SECRET",""))
RURI = "https://sadox1.streamlit.app/"
DB   = "chat.db"
ADMIN_EMAIL = "amarisaad033@gmail.com"
SID  = "sid"

COLORS  = ["#5865f2","#7c3aed","#0ea5e9","#e11d48","#10b981","#f59e0b","#ec4899","#14b8a6"]
AVATARS = ["👤","🦊","🐼","🦁","🐺","🦋","🌸","⚡","🚀","🎮","🎯","🌙","🔥","💎","🎭","🌊","🦅","🐉","🌺","🎪"]

# ═══════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════
def db():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
            avatar TEXT DEFAULT '👤', avatar_url TEXT DEFAULT '',
            color TEXT DEFAULT '#5865f2', provider TEXT DEFAULT 'local',
            password_hash TEXT DEFAULT '',
            status TEXT DEFAULT 'offline', bio TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0, created TEXT DEFAULT(datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions(
            token TEXT PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            expires TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS servers(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, icon TEXT DEFAULT '💬',
            description TEXT DEFAULT '', owner INTEGER REFERENCES users(id),
            banner_color TEXT DEFAULT '#5865f2',
            created TEXT DEFAULT(datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS channel_categories(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER REFERENCES servers(id),
            name TEXT NOT NULL, position INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS channels(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER REFERENCES servers(id),
            category_id INTEGER REFERENCES channel_categories(id),
            name TEXT NOT NULL, icon TEXT DEFAULT '💬',
            topic TEXT DEFAULT '', type TEXT DEFAULT 'text',
            position INTEGER DEFAULT 0,
            created TEXT DEFAULT(datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER REFERENCES channels(id),
            user_id INTEGER REFERENCES users(id),
            content TEXT NOT NULL, reply_to INTEGER DEFAULT NULL,
            edited INTEGER DEFAULT 0, pinned INTEGER DEFAULT 0,
            created TEXT DEFAULT(datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS memberships(
            user_id INTEGER REFERENCES users(id),
            server_id INTEGER REFERENCES servers(id),
            role TEXT DEFAULT 'member',
            nickname TEXT DEFAULT '',
            PRIMARY KEY(user_id, server_id)
        );
        CREATE TABLE IF NOT EXISTS reactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER REFERENCES messages(id),
            user_id INTEGER REFERENCES users(id),
            emoji TEXT NOT NULL,
            UNIQUE(message_id, user_id, emoji)
        );
        CREATE TABLE IF NOT EXISTS direct_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user INTEGER REFERENCES users(id),
            to_user INTEGER REFERENCES users(id),
            content TEXT NOT NULL, read INTEGER DEFAULT 0,
            created TEXT DEFAULT(datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS typing(
            user_id INTEGER, channel_id INTEGER,
            updated TEXT DEFAULT(datetime('now')),
            PRIMARY KEY(user_id, channel_id)
        );
        CREATE TABLE IF NOT EXISTS channel_reads(
            user_id INTEGER, channel_id INTEGER,
            last_read_id INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, channel_id)
        );
        """)
        c.execute("UPDATE users SET is_admin=1 WHERE email=?", (ADMIN_EMAIL,))
        if c.execute("SELECT COUNT(*) FROM servers").fetchone()[0] == 0:
            _seed(c)
    _migrate_db()

def _seed(c):
    c.execute("INSERT OR IGNORE INTO users(email,name,avatar,color,provider,bio) VALUES(?,?,?,?,?,?)",
              ("system@streamline.app","StreamLine","💬","#5865f2","system","System"))
    su = c.execute("SELECT id FROM users WHERE email='system@streamline.app'").fetchone()[0]
    c.execute("INSERT INTO servers(name,icon,owner,description,banner_color) VALUES(?,?,?,?,?)",
              ("StreamLine HQ","💬",su,"Welcome to StreamLine!","#5865f2"))
    sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
    for cn,cp in [("WELCOME",0),("INFORMATION",1),("COMMUNITY",2)]:
        c.execute("INSERT INTO channel_categories(server_id,name,position) VALUES(?,?,?)",(sid,cn,cp))
    cats = {r["name"]:r["id"] for r in c.execute("SELECT * FROM channel_categories WHERE server_id=?",(sid,)).fetchall()}
    chans = [
        ("rules","📋","Read before chatting","WELCOME",0),
        ("announcements","📢","Important updates","WELCOME",1),
        ("welcome","👋","Introduce yourself","WELCOME",2),
        ("general","💬","General chat","COMMUNITY",0),
        ("random","🎲","Off-topic","COMMUNITY",1),
        ("dev","💻","Developer talk","INFORMATION",0),
    ]
    for name,icon,topic,cat,pos in chans:
        c.execute("INSERT INTO channels(server_id,category_id,name,icon,topic,position) VALUES(?,?,?,?,?,?)",
                  (sid,cats[cat],name,icon,topic,pos))
    gcid = c.execute("SELECT id FROM channels WHERE name='general' AND server_id=?",(sid,)).fetchone()[0]
    c.execute("INSERT INTO messages(channel_id,user_id,content) VALUES(?,?,?)",
              (gcid,su,"👋 Welcome to **StreamLine**! Sign in with Google to get started. 🚀"))
    c.execute("INSERT OR IGNORE INTO memberships(user_id,server_id,role) VALUES(?,?,?)",(su,sid,"member"))

# ═══════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════
def create_session(uid):
    tok = secrets.token_hex(32)
    exp = (datetime.utcnow()+timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    with db() as c: c.execute("INSERT INTO sessions(token,user_id,expires) VALUES(?,?,?)",(tok,uid,exp))
    return tok

def validate_session(tok):
    if not tok: return None
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with db() as c:
        r = c.execute("SELECT user_id FROM sessions WHERE token=? AND expires>?",(tok,now)).fetchone()
    return get_user(r["user_id"]) if r else None

def del_session(tok):
    if tok:
        with db() as c: c.execute("DELETE FROM sessions WHERE token=?",(tok,))

def gtok(): return st.session_state.get("_tok") or st.query_params.get(SID)
def stok(t): st.session_state["_tok"]=t; st.query_params[SID]=t

# ═══════════════════════════════════════════════════
# USERS
# ═══════════════════════════════════════════════════
def get_user(uid):
    with db() as c: r = c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    return dict(r) if r else None

def get_all_users():
    with db() as c: return [dict(r) for r in c.execute("SELECT * FROM users WHERE provider!='system'").fetchall()]

def upsert_google(email, name, pic=""):
    email = email.lower()
    is_admin = 1 if email==ADMIN_EMAIL else 0
    color = random.choice(COLORS)
    with db() as c:
        c.execute("""INSERT INTO users(email,name,avatar,avatar_url,color,provider,is_admin)
                     VALUES(?,?,'G',?,?,'google',?)
                     ON CONFLICT(email) DO UPDATE SET
                       name=excluded.name, avatar_url=excluded.avatar_url,
                       is_admin=MAX(users.is_admin,excluded.is_admin)""",
                  (email,name,pic,color,is_admin))
        row = c.execute("SELECT * FROM users WHERE email=?",(email,)).fetchone()
        uid = row["id"]
        for s in c.execute("SELECT id FROM servers WHERE name!='system'").fetchall():
            c.execute("INSERT OR IGNORE INTO memberships(user_id,server_id,role) VALUES(?,?,?)",(uid,s["id"],"member"))
    return dict(row)

def _migrate_db():
    """Add password_hash column to existing databases that predate this feature."""
    with db() as c:
        cols = [r[1] for r in c.execute("PRAGMA table_info(users)").fetchall()]
        if "password_hash" not in cols:
            c.execute("ALTER TABLE users ADD COLUMN password_hash TEXT DEFAULT ''")

def _hash(pw):
    import hashlib
    return hashlib.sha256(pw.encode()).hexdigest()

def register_local(email, name, avatar, password):
    email = email.lower().strip()
    if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$', email):
        raise ValueError("Invalid email address.")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters.")
    if not name.strip():
        raise ValueError("Display name cannot be empty.")
    is_admin = 1 if email == ADMIN_EMAIL else 0
    color = random.choice(COLORS)
    pw_hash = _hash(password)
    with db() as c:
        existing = c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            raise ValueError("An account with this email already exists.")
        c.execute(
            "INSERT INTO users(email,name,avatar,color,provider,password_hash,is_admin) VALUES(?,?,?,?,'local',?,?)",
            (email, name.strip(), avatar, color, pw_hash, is_admin)
        )
        uid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        for s in c.execute("SELECT id FROM servers WHERE name!='system'").fetchall():
            c.execute("INSERT OR IGNORE INTO memberships(user_id,server_id,role) VALUES(?,?,?)", (uid, s["id"], "member"))
        return dict(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())

def login_local(email, password):
    email = email.lower().strip()
    if not email or not password:
        raise ValueError("Email and password are required.")
    pw_hash = _hash(password)
    with db() as c:
        row = c.execute(
            "SELECT * FROM users WHERE email=? AND password_hash=? AND provider='local'",
            (email, pw_hash)
        ).fetchone()
    if not row:
        raise ValueError("Invalid email or password.")
    return dict(row)

def change_password(uid, old_pw, new_pw):
    if len(new_pw) < 6:
        raise ValueError("New password must be at least 6 characters.")
    old_hash = _hash(old_pw)
    with db() as c:
        row = c.execute("SELECT password_hash, provider FROM users WHERE id=?", (uid,)).fetchone()
        if not row or row["provider"] != "local":
            raise ValueError("Password change is only available for local accounts.")
        if row["password_hash"] != old_hash:
            raise ValueError("Current password is incorrect.")
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (_hash(new_pw), uid))

def update_profile(uid, name, avatar, bio):
    with db() as c: c.execute("UPDATE users SET name=?,avatar=?,bio=? WHERE id=?",(name,avatar,bio,uid))

def heartbeat(uid):
    with db() as c:
        c.execute("UPDATE users SET status='online' WHERE id=?",(uid,))
        c.execute("""UPDATE users SET status='offline'
            WHERE id!=? AND status='online' AND NOT EXISTS(
                SELECT 1 FROM sessions WHERE user_id=users.id AND expires>datetime('now')
            )""",(uid,))

# ═══════════════════════════════════════════════════
# SERVERS / CHANNELS / CATEGORIES
# ═══════════════════════════════════════════════════
def get_servers(uid=None):
    with db() as c:
        if uid:
            return [dict(r) for r in c.execute(
                "SELECT s.* FROM servers s JOIN memberships m ON s.id=m.server_id WHERE m.user_id=?",(uid,)).fetchall()]
        return [dict(r) for r in c.execute("SELECT * FROM servers").fetchall()]

def get_categories(sid):
    with db() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM channel_categories WHERE server_id=? ORDER BY position",(sid,)).fetchall()]

def get_channels(sid, cat_id=None):
    with db() as c:
        if cat_id is not None:
            return [dict(r) for r in c.execute(
                "SELECT * FROM channels WHERE server_id=? AND category_id=? ORDER BY position",(sid,cat_id)).fetchall()]
        return [dict(r) for r in c.execute(
            "SELECT * FROM channels WHERE server_id=? ORDER BY category_id,position",(sid,)).fetchall()]

def get_all_channels_flat(sid):
    return get_channels(sid)

def get_members(sid):
    with db() as c:
        return [dict(r) for r in c.execute("""
            SELECT u.id,u.name,u.avatar,u.avatar_url,u.color,u.status,u.bio,u.is_admin,mb.role,mb.nickname
            FROM memberships mb JOIN users u ON u.id=mb.user_id
            WHERE mb.server_id=? AND u.provider!='system'
            ORDER BY mb.role DESC,u.name""",(sid,)).fetchall()]

def join_server(uid, sid):
    with db() as c: c.execute("INSERT OR IGNORE INTO memberships(user_id,server_id,role) VALUES(?,?,?)",(uid,sid,"member"))

def create_server(name, icon, owner, desc="", color="#5865f2"):
    with db() as c:
        c.execute("INSERT INTO servers(name,icon,owner,description,banner_color) VALUES(?,?,?,?,?)",(name,icon,owner,desc,color))
        sid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO channel_categories(server_id,name,position) VALUES(?,?,?)",(sid,"CHANNELS",0))
        catid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT INTO channels(server_id,category_id,name,icon,topic) VALUES(?,?,?,?,?)",(sid,catid,"general","💬","General"))
        c.execute("INSERT OR IGNORE INTO memberships(user_id,server_id,role) VALUES(?,?,?)",(owner,sid,"admin"))

def create_category(sid, name):
    with db() as c:
        pos = c.execute("SELECT COUNT(*) FROM channel_categories WHERE server_id=?",(sid,)).fetchone()[0]
        c.execute("INSERT INTO channel_categories(server_id,name,position) VALUES(?,?,?)",(sid,name,pos))

def create_channel(sid, cat_id, name, icon="💬", topic=""):
    with db() as c:
        pos = c.execute("SELECT COUNT(*) FROM channels WHERE category_id=?",(cat_id,)).fetchone()[0]
        c.execute("INSERT INTO channels(server_id,category_id,name,icon,topic,position) VALUES(?,?,?,?,?,?)",
                  (sid,cat_id,name,icon,topic,pos))

def get_server_stats(sid):
    with db() as c:
        msgs = c.execute("SELECT COUNT(*) FROM messages m JOIN channels ch ON ch.id=m.channel_id WHERE ch.server_id=?",(sid,)).fetchone()[0]
        members = c.execute("SELECT COUNT(*) FROM memberships WHERE server_id=?",(sid,)).fetchone()[0]
        chs = c.execute("SELECT COUNT(*) FROM channels WHERE server_id=?",(sid,)).fetchone()[0]
    return {"messages":msgs,"members":members,"channels":chs}

# ═══════════════════════════════════════════════════
# MESSAGES
# ═══════════════════════════════════════════════════
def get_messages(cid, limit=80, search=""):
    with db() as c:
        if search:
            rows = c.execute("""SELECT m.id,m.content,m.created,m.edited,m.pinned,m.reply_to,
                u.name AS username,u.color,u.avatar_url,u.id AS user_id
                FROM messages m JOIN users u ON u.id=m.user_id
                WHERE m.channel_id=? AND m.content LIKE ? ORDER BY m.id DESC LIMIT ?""",
                (cid,f"%{search}%",limit)).fetchall()
        else:
            rows = c.execute("""SELECT m.id,m.content,m.created,m.edited,m.pinned,m.reply_to,
                u.name AS username,u.color,u.avatar_url,u.id AS user_id
                FROM messages m JOIN users u ON u.id=m.user_id
                WHERE m.channel_id=? ORDER BY m.id DESC LIMIT ?""",(cid,limit)).fetchall()
    return list(reversed([dict(r) for r in rows]))

def post_message(cid, uid, content, reply_to=None):
    with db() as c:
        c.execute("INSERT INTO messages(channel_id,user_id,content,reply_to) VALUES(?,?,?,?)",(cid,uid,content,reply_to))
        mid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        c.execute("INSERT OR REPLACE INTO channel_reads(user_id,channel_id,last_read_id) VALUES(?,?,?)",(uid,cid,mid))

def edit_message(mid, uid, content):
    with db() as c: c.execute("UPDATE messages SET content=?,edited=1 WHERE id=? AND user_id=?",(content,mid,uid))

def delete_message(mid, uid, is_admin=False):
    with db() as c:
        if is_admin: c.execute("DELETE FROM messages WHERE id=?",(mid,))
        else: c.execute("DELETE FROM messages WHERE id=? AND user_id=?",(mid,uid))

def pin_message(mid):
    with db() as c: c.execute("UPDATE messages SET pinned=1-pinned WHERE id=?",(mid,))

def get_pinned(cid):
    with db() as c:
        return [dict(r) for r in c.execute("""
            SELECT m.id,m.content,m.created,u.name AS username,u.color
            FROM messages m JOIN users u ON u.id=m.user_id
            WHERE m.channel_id=? AND m.pinned=1 ORDER BY m.id DESC""",(cid,)).fetchall()]

def get_message_count(cid):
    with db() as c: return c.execute("SELECT COUNT(*) FROM messages WHERE channel_id=?",(cid,)).fetchone()[0]

def get_unread_count(uid, cid):
    with db() as c:
        last = c.execute("SELECT last_read_id FROM channel_reads WHERE user_id=? AND channel_id=?",(uid,cid)).fetchone()
        last_id = last["last_read_id"] if last else 0
        return c.execute("SELECT COUNT(*) FROM messages WHERE channel_id=? AND id>? AND user_id!=?",(cid,last_id,uid)).fetchone()[0]

def mark_channel_read(uid, cid):
    with db() as c:
        last = c.execute("SELECT MAX(id) FROM messages WHERE channel_id=?",(cid,)).fetchone()[0] or 0
        c.execute("INSERT OR REPLACE INTO channel_reads(user_id,channel_id,last_read_id) VALUES(?,?,?)",(uid,cid,last))

def add_reaction(mid, uid, emoji):
    try:
        with db() as c: c.execute("INSERT INTO reactions(message_id,user_id,emoji) VALUES(?,?,?)",(mid,uid,emoji))
    except sqlite3.IntegrityError:
        with db() as c: c.execute("DELETE FROM reactions WHERE message_id=? AND user_id=? AND emoji=?",(mid,uid,emoji))

def get_reactions(cid):
    with db() as c:
        rows = c.execute("""SELECT r.message_id,r.emoji,COUNT(*) as cnt
            FROM reactions r JOIN messages m ON r.message_id=m.id
            WHERE m.channel_id=? GROUP BY r.message_id,r.emoji""",(cid,)).fetchall()
    res={}
    for r in rows: res.setdefault(r["message_id"],{})[r["emoji"]]=r["cnt"]
    return res

# ═══════════════════════════════════════════════════
# TYPING
# ═══════════════════════════════════════════════════
def set_typing(uid, cid):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO typing(user_id,channel_id,updated) VALUES(?,?,datetime('now'))",(uid,cid))

def get_typing(cid, uid):
    with db() as c:
        rows = c.execute("""SELECT u.name FROM typing t JOIN users u ON u.id=t.user_id
            WHERE t.channel_id=? AND t.user_id!=? AND t.updated>datetime('now','-5 seconds')""",(cid,uid)).fetchall()
    return [r["name"] for r in rows]

# ═══════════════════════════════════════════════════
# DMs
# ═══════════════════════════════════════════════════
def send_dm(f, t, content):
    with db() as c: c.execute("INSERT INTO direct_messages(from_user,to_user,content) VALUES(?,?,?)",(f,t,content))

def get_dms(u1, u2, limit=60):
    with db() as c:
        rows = c.execute("""SELECT dm.*,uf.name AS from_name,uf.color AS from_color,uf.avatar_url AS from_pic
            FROM direct_messages dm JOIN users uf ON uf.id=dm.from_user
            WHERE (dm.from_user=? AND dm.to_user=?) OR (dm.from_user=? AND dm.to_user=?)
            ORDER BY dm.id DESC LIMIT ?""",(u1,u2,u2,u1,limit)).fetchall()
    return list(reversed([dict(r) for r in rows]))

def unread_total(uid):
    with db() as c: return c.execute("SELECT COUNT(*) FROM direct_messages WHERE to_user=? AND read=0",(uid,)).fetchone()[0]

def unread_from(fid, tid):
    with db() as c: return c.execute("SELECT COUNT(*) FROM direct_messages WHERE from_user=? AND to_user=? AND read=0",(fid,tid)).fetchone()[0]

def mark_dm_read(fid, tid):
    with db() as c: c.execute("UPDATE direct_messages SET read=1 WHERE from_user=? AND to_user=?",(fid,tid))

def get_dm_convos(uid):
    with db() as c:
        rows = c.execute("""SELECT DISTINCT
            CASE WHEN dm.from_user=? THEN dm.to_user ELSE dm.from_user END AS other_id,
            u.name,u.avatar,u.avatar_url,u.color,u.status, MAX(dm.created) AS last_msg
            FROM direct_messages dm
            JOIN users u ON u.id=CASE WHEN dm.from_user=? THEN dm.to_user ELSE dm.from_user END
            WHERE dm.from_user=? OR dm.to_user=?
            GROUP BY other_id ORDER BY last_msg DESC""",(uid,uid,uid,uid)).fetchall()
    return [dict(r) for r in rows]

# ═══════════════════════════════════════════════════
# GOOGLE OAUTH
# ═══════════════════════════════════════════════════
def google_url():
    import urllib.parse as ul
    p = {"client_id":GID,"redirect_uri":RURI,"response_type":"code",
         "scope":"openid email profile","access_type":"offline","prompt":"consent"}
    return "https://accounts.google.com/o/oauth2/v2/auth?"+ul.urlencode(p)

def google_cb(code):
    import requests as rq, base64 as _b64, json as _json
    resp = rq.post("https://oauth2.googleapis.com/token",data={
        "code":code,"client_id":GID,"client_secret":GSEC,
        "redirect_uri":RURI,"grant_type":"authorization_code"},timeout=10).json()
    if "error" in resp: raise RuntimeError(f"{resp['error']}: {resp.get('error_description','')}")
    raw_id = resp["id_token"]
    pad = raw_id.split(".")[1]; pad += "=" * (4 - len(pad) % 4)
    info = _json.loads(_b64.urlsafe_b64decode(pad))
    if info.get("aud") != GID: raise RuntimeError("Token audience mismatch")
    if not info.get("email"): raise RuntimeError("No email in token")
    return upsert_google(info["email"],info.get("name",info["email"]),info.get("picture",""))

# ═══════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════
def ini(name):
    p=name.strip().split()
    if len(p)>=2: return (p[0][0]+p[1][0]).upper()
    return name[:2].upper() if len(name)>=2 else name[0].upper()

def fmt(s):
    try:
        dt=datetime.strptime(s[:19],"%Y-%m-%d %H:%M:%S")
        d=datetime.utcnow()-dt
        if d.days==0: return dt.strftime("%H:%M")
        if d.days==1: return "Yesterday "+dt.strftime("%H:%M")
        return dt.strftime("%d/%m/%y")
    except: return ""

def fmt_full(s):
    try: return datetime.strptime(s[:19],"%Y-%m-%d %H:%M:%S").strftime("%d %b %Y %H:%M")
    except: return s

def mdparse(text):
    import html as ht
    text=ht.escape(text)
    text=re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',text)
    text=re.sub(r'\*(.+?)\*',r'<em>\1</em>',text)
    text=re.sub(r'`(.+?)`',r'<code>\1</code>',text)
    text=re.sub(r'(https?://[^\s<>]+)',r'<a href="\1" target="_blank">\1</a>',text)
    return text

def avatar_html(u, size=40, font=14):
    url = u.get("avatar_url","") if isinstance(u,dict) else ""
    color = u.get("color","#5865f2") if isinstance(u,dict) else "#5865f2"
    name  = u.get("name","?") if isinstance(u,dict) else str(u)
    label = ini(name)
    if url:
        return f'<img src="{url}" style="width:{size}px;height:{size}px;border-radius:50%;object-fit:cover">'
    return f'<div style="width:{size}px;height:{size}px;border-radius:50%;background:{color};display:flex;align-items:center;justify-content:center;font-size:{font}px;font-weight:700;color:#fff;flex-shrink:0">{label}</div>'

# ═══════════════════════════════════════════════════
# CSS — Full Discord Layout
# ═══════════════════════════════════════════════════
def css():
    st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=gg+sans:wght@400;500;600;700&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

*{box-sizing:border-box;margin:0;padding:0;}
html,body,[class*="css"]{font-family:'Inter',system-ui,sans-serif!important;}
#MainMenu,footer,header,[data-testid="stToolbar"]{visibility:hidden!important;display:none!important;}
.block-container{padding:0!important;max-width:100%!important;}
.stApp,[data-testid="stAppViewContainer"]{background:#313338!important;}
[data-testid="stVerticalBlock"]{gap:0!important;}
[data-testid="stSidebar"]{display:none!important;}
::-webkit-scrollbar{width:4px;height:4px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:#1a1b1e;border-radius:4px;}

.stTextInput input{
  background:#1e1f22!important;border:none!important;border-radius:8px!important;
  color:#dbdee1!important;font-size:14px!important;padding:10px 14px!important;
}
.stTextInput input::placeholder{color:#4e5058!important;}
.stTextInput input:focus{box-shadow:0 0 0 2px #5865f2!important;}
.stTextInput label{color:#b5bac1!important;font-size:11px!important;font-weight:600!important;letter-spacing:.5px!important;text-transform:uppercase!important;}
.stTextArea textarea{background:#1e1f22!important;border:none!important;border-radius:8px!important;color:#dbdee1!important;}
.stTextArea label{color:#b5bac1!important;font-size:11px!important;}
/* All buttons: transparent */
.stButton button,
.stButton>button,
[data-testid="stBaseButton-secondary"],
button[kind="secondary"] {
  background:transparent!important;
  background-color:transparent!important;
  color:#b5bac1!important;
  border:1px solid rgba(255,255,255,0.10)!important;
  border-radius:4px!important;
  font-weight:500!important;
  font-size:12px!important;
  padding:4px 10px!important;
  transition:all .15s!important;
  box-shadow:none!important;
}
.stButton button:hover,
.stButton>button:hover,
[data-testid="stBaseButton-secondary"]:hover {
  background:rgba(255,255,255,0.07)!important;
  background-color:rgba(255,255,255,0.07)!important;
  color:#fff!important;
  border-color:rgba(255,255,255,0.18)!important;
}
/* Primary/Send button stays blue */
[data-testid="stBaseButton-primary"],
button[kind="primary"],
.stButton button[kind="primary"] {
  background:#5865f2!important;
  background-color:#5865f2!important;
  color:#fff!important;
  border:none!important;
  box-shadow:none!important;
}
[data-testid="stBaseButton-primary"]:hover,
button[kind="primary"]:hover {
  background:#4752c4!important;
  background-color:#4752c4!important;
}
.stSelectbox [data-baseweb="select"]>div{background:#1e1f22!important;border:none!important;border-radius:8px!important;color:#dbdee1!important;}
[data-baseweb="popover"],[data-baseweb="menu"]{background:#18191c!important;border:1px solid rgba(255,255,255,0.06)!important;border-radius:8px!important;}
[role="option"]{color:#b5bac1!important;}[role="option"]:hover{background:#404249!important;color:#fff!important;}
.stTabs [data-baseweb="tab-list"]{background:transparent!important;border-bottom:2px solid rgba(255,255,255,0.06)!important;gap:0!important;}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:#b5bac1!important;border-radius:0!important;font-size:14px!important;font-weight:500!important;padding:10px 16px!important;border-bottom:2px solid transparent!important;margin-bottom:-2px!important;}
.stTabs [aria-selected="true"]{color:#fff!important;border-bottom-color:#5865f2!important;}
.stTabs [data-baseweb="tab-highlight"]{display:none!important;}
.stTabs [data-baseweb="tab-panel"]{padding:16px 0 0!important;}
.stAlert{border-radius:4px!important;}
.stCheckbox label{color:#b5bac1!important;}
.stLinkButton a{
  background:#4e9a51!important;color:#fff!important;border:none!important;
  border-radius:4px!important;font-weight:600!important;font-size:15px!important;
  padding:12px 20px!important;transition:background .15s!important;
  display:flex!important;align-items:center!important;justify-content:center!important;gap:10px!important;
}
.stLinkButton a:hover{background:#3d8140!important;}

/* Auth page extras */
.dc-auth-or{
  text-align:center;font-size:11px;font-weight:600;letter-spacing:.08em;
  color:#4e5058;margin:14px 0 10px;position:relative;
}
.dc-auth-or::before,.dc-auth-or::after{
  content:'';position:absolute;top:50%;width:38%;height:1px;
  background:rgba(255,255,255,0.08);
}
.dc-auth-or::before{left:0;}
.dc-auth-or::after{right:0;}
.dc-google-btn{
  display:flex;align-items:center;justify-content:center;gap:10px;
  background:#1e1f22;color:#dbdee1;border:1px solid rgba(255,255,255,0.10);
  border-radius:6px;padding:11px 16px;font-size:14px;font-weight:500;
  text-decoration:none;transition:background .15s;cursor:pointer;width:100%;
}
.dc-google-btn:hover{background:#2e2f35;color:#fff;}

/* ── Discord Layout ── */
.dc-layout{display:flex;height:100vh;overflow:hidden;background:#313338;}

/* Server rail */
.dc-rail{width:56px;min-width:56px;background:#1e1f22;display:flex;flex-direction:column;align-items:center;padding:6px 0;gap:2px;overflow-y:auto;overflow-x:hidden;}
.dc-rail-sep{width:28px;height:2px;background:#3a3c42;border-radius:1px;margin:3px 0;}
.dc-srv-btn{width:40px;height:40px;border-radius:50%;background:#313338;display:flex;align-items:center;justify-content:center;font-size:17px;cursor:pointer;transition:all .15s;position:relative;flex-shrink:0;}
.dc-srv-btn:hover{border-radius:16px;background:#5865f2;}
.dc-srv-btn.active{border-radius:16px;background:#5865f2;}
.dc-srv-pill{position:absolute;left:-4px;top:50%;transform:translateY(-50%);width:4px;background:#fff;border-radius:0 4px 4px 0;transition:all .15s;}
.dc-srv-btn:hover .dc-srv-pill{height:20px;}
.dc-srv-btn.active .dc-srv-pill{height:40px;}
.dc-srv-tip{position:absolute;left:60px;background:#111214;color:#fff;font-size:14px;font-weight:600;padding:8px 12px;border-radius:8px;white-space:nowrap;z-index:100;pointer-events:none;opacity:0;transition:opacity .1s;}
.dc-srv-btn:hover .dc-srv-tip{opacity:1;}
.dc-srv-notif{position:absolute;bottom:0;right:0;width:16px;height:16px;background:#ed4245;border-radius:50%;border:3px solid #1e1f22;font-size:9px;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;}

/* Channel sidebar */
.dc-sidebar{width:240px;min-width:240px;background:#2b2d31;display:flex;flex-direction:column;overflow:hidden;}
.dc-sidebar-hdr{padding:0 12px;height:36px;display:flex;align-items:center;border-bottom:1px solid rgba(0,0,0,0.3);cursor:pointer;flex-shrink:0;}
.dc-sidebar-hdr:hover{background:#35373c;}
.dc-sidebar-title{font-size:13px;font-weight:700;color:#f2f3f5;flex:1;}
.dc-sidebar-body{flex:1;overflow-y:auto;padding:8px 0;}
.dc-category{padding:16px 8px 4px 16px;font-size:11px;font-weight:700;letter-spacing:.7px;color:#8e9297;text-transform:uppercase;display:flex;align-items:center;gap:4px;cursor:pointer;}
.dc-category:hover{color:#dbdee1;}
.dc-ch-row{display:flex;align-items:center;gap:6px;padding:4px 6px 4px 12px;border-radius:4px;margin:0 6px;cursor:pointer;color:#8e9297;font-size:13px;font-weight:500;transition:all .1s;position:relative;}
.dc-ch-row:hover{background:#35373c;color:#dbdee1;}
.dc-ch-row.active{background:#404249;color:#f2f3f5;}
.dc-ch-row.unread{color:#f2f3f5;font-weight:600;}
.dc-ch-icon{font-size:14px;flex-shrink:0;}
.dc-ch-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dc-ch-badge{background:#ed4245;color:#fff;font-size:10px;font-weight:700;padding:2px 5px;border-radius:8px;min-width:16px;text-align:center;}
.dc-sidebar-footer{background:#232428;padding:5px 6px;display:flex;align-items:center;gap:6px;flex-shrink:0;}
.dc-footer-av{position:relative;cursor:pointer;}
.dc-footer-dot{position:absolute;bottom:-1px;right:-1px;width:12px;height:12px;border-radius:50%;border:3px solid #232428;}
.dc-footer-info{flex:1;min-width:0;cursor:pointer;}
.dc-footer-name{font-size:11px;font-weight:600;color:#f2f3f5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dc-footer-tag{font-size:10px;color:#b5bac1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dc-footer-icons{display:flex;gap:2px;}
.dc-footer-icon{width:32px;height:32px;border-radius:4px;display:flex;align-items:center;justify-content:center;color:#b5bac1;font-size:16px;cursor:pointer;transition:all .1s;}
.dc-footer-icon:hover{background:#35373c;color:#dbdee1;}

/* Main content */
.dc-main{flex:1;display:flex;flex-direction:column;overflow:hidden;background:#313338;}

/* Topbar */
.dc-topbar{height:36px;display:flex;align-items:center;padding:0 10px;gap:6px;border-bottom:1px solid rgba(0,0,0,0.3);flex-shrink:0;background:#313338;}
.dc-topbar-icon{color:#8e9297;font-size:16px;}
.dc-topbar-name{font-size:16px;font-weight:700;color:#f2f3f5;}
.dc-topbar-div{width:1px;height:24px;background:rgba(255,255,255,0.08);margin:0 8px;}
.dc-topbar-topic{font-size:14px;color:#8e9297;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dc-topbar-actions{display:flex;gap:4px;margin-left:auto;}
.dc-topbar-btn{width:36px;height:36px;border-radius:4px;display:flex;align-items:center;justify-content:center;color:#b5bac1;font-size:18px;cursor:pointer;transition:all .1s;}
.dc-topbar-btn:hover{background:#35373c;color:#dbdee1;}
.dc-topbar-btn.active{color:#f2f3f5;}

/* Feed */
.dc-feed{flex:1;overflow-y:auto;padding:16px 0 8px;}
.dc-welcome{padding:10px 12px 16px;}
.dc-welcome-av{width:48px;height:48px;border-radius:50%;background:#5865f2;display:flex;align-items:center;justify-content:center;font-size:20px;color:#fff;font-weight:700;margin-bottom:10px;}
.dc-welcome-title{font-size:22px;font-weight:700;color:#f2f3f5;margin-bottom:6px;}
.dc-welcome-sub{font-size:14px;color:#8e9297;line-height:1.5;}
.dc-day-sep{display:flex;align-items:center;gap:12px;margin:16px 0;padding:0 16px;}
.dc-day-sep::before,.dc-day-sep::after{content:'';flex:1;height:1px;background:rgba(255,255,255,0.06);}
.dc-day-label{font-size:12px;font-weight:600;color:#8e9297;white-space:nowrap;}
.dc-msg{display:flex;gap:16px;padding:2px 16px;border-radius:0;}
.dc-msg:hover{background:rgba(4,4,5,0.07);}
.dc-msg-full{padding-top:16px;}
.dc-msg-full .dc-msg-av{flex-shrink:0;}
.dc-msg-grouped{padding-left:72px;}
.dc-msg-body{flex:1;min-width:0;}
.dc-msg-header{display:flex;align-items:baseline;gap:8px;margin-bottom:2px;}
.dc-msg-author{font-size:15px;font-weight:600;color:#f2f3f5;cursor:pointer;}
.dc-msg-author:hover{text-decoration:underline;}
.dc-msg-ts{font-size:12px;color:#4e5058;}
.dc-msg-edited{font-size:11px;color:#4e5058;font-style:italic;}
.dc-msg-pin{font-size:10px;color:#faa61a;background:rgba(250,166,26,0.1);border-radius:3px;padding:1px 5px;}
.dc-msg-text{font-size:15px;color:#dbdee1;line-height:1.5;word-break:break-word;}
.dc-msg-text code{background:#2b2d31;border-radius:3px;padding:0 4px;font-size:13px;color:#b9befe;font-family:'Courier New',monospace;}
.dc-msg-text a{color:#00a8fc;text-decoration:none;}
.dc-msg-text a:hover{text-decoration:underline;}
.dc-msg-text strong{color:#f2f3f5;}
.dc-msg-reply{display:flex;align-items:center;gap:6px;font-size:13px;color:#8e9297;margin-bottom:4px;padding-left:4px;border-left:2px solid #4e5058;}
.dc-reactions{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;}
.dc-rxn{display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:2px 8px;font-size:13px;color:#dbdee1;cursor:pointer;}
.dc-rxn:hover{background:rgba(255,255,255,0.1);}
.dc-rxn-n{font-size:12px;font-weight:600;color:#b9befe;}
.dc-msg-actions{position:absolute;right:16px;top:-16px;background:#2b2d31;border:1px solid rgba(255,255,255,0.06);border-radius:4px;display:flex;gap:2px;padding:4px;}
.dc-act-btn{width:32px;height:32px;border-radius:4px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:16px;color:#b5bac1;}
.dc-act-btn:hover{background:#404249;color:#fff;}

/* Composer */
.dc-composer-wrap{padding:0 10px 16px;flex-shrink:0;}
.dc-composer{background:#383a40;border-radius:8px;display:flex;align-items:center;gap:8px;padding:0 16px;}
.dc-composer-input{flex:1;background:transparent;border:none;outline:none;color:#dbdee1;font-size:15px;padding:12px 0;font-family:'Inter',system-ui,sans-serif;}
.dc-composer-input::placeholder{color:#4e5058;}
.dc-composer-btn{color:#b5bac1;font-size:20px;cursor:pointer;padding:4px;border-radius:4px;transition:color .1s;}
.dc-composer-btn:hover{color:#dbdee1;}
.dc-typing{height:24px;padding:0 16px 4px;font-size:13px;color:#b5bac1;display:flex;align-items:center;gap:4px;}
.dc-typing-dots{display:flex;gap:2px;}
.dc-typing-dot{width:4px;height:4px;border-radius:50%;background:#b5bac1;animation:dc-bounce .6s infinite;}
.dc-typing-dot:nth-child(2){animation-delay:.1s;}
.dc-typing-dot:nth-child(3){animation-delay:.2s;}
@keyframes dc-bounce{0%,60%,100%{transform:translateY(0);}30%{transform:translateY(-4px);}}

/* Member panel */
.dc-members{width:200px;min-width:200px;background:#2b2d31;overflow-y:auto;padding:12px 0;}
.dc-members-section{padding:12px 8px 3px 12px;font-size:10px;font-weight:700;letter-spacing:.7px;color:#8e9297;text-transform:uppercase;}
.dc-member-row{display:flex;align-items:center;gap:8px;padding:4px 6px;border-radius:4px;margin:0 6px;cursor:pointer;transition:background .1s;}
.dc-member-row:hover{background:#35373c;}
.dc-member-av{position:relative;flex-shrink:0;}
.dc-member-dot{position:absolute;bottom:-1px;right:-1px;width:10px;height:10px;border-radius:50%;border:2px solid #2b2d31;}
.dc-member-info{min-width:0;}
.dc-member-name{font-size:13px;font-weight:500;color:#8e9297;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.dc-member-row:hover .dc-member-name{color:#f2f3f5;}
.dc-member-badge{font-size:10px;color:#faa61a;font-weight:700;}

/* DM view */
.dc-dm-list{width:240px;min-width:240px;background:#2b2d31;display:flex;flex-direction:column;}
.dc-dm-hdr{padding:0 12px;height:48px;display:flex;align-items:center;border-bottom:1px solid rgba(0,0,0,0.3);flex-shrink:0;}
.dc-dm-hdr-title{font-size:16px;font-weight:700;color:#f2f3f5;}
.dc-dm-search{background:#1e1f22;border-radius:4px;padding:4px 8px;margin:8px 8px 4px;font-size:14px;color:#dbdee1;}
.dc-dm-section{padding:8px 8px 4px 12px;font-size:11px;font-weight:700;letter-spacing:.7px;color:#8e9297;text-transform:uppercase;}
.dc-dm-row{display:flex;align-items:center;gap:10px;padding:6px 8px;border-radius:4px;margin:0 4px;cursor:pointer;transition:background .1s;}
.dc-dm-row:hover{background:#35373c;}
.dc-dm-row.active{background:#404249;}
.dc-dm-name{font-size:15px;font-weight:500;color:#8e9297;}
.dc-dm-row:hover .dc-dm-name,.dc-dm-row.active .dc-dm-name{color:#f2f3f5;}

/* Profile popup */
.dc-profile-popup{background:#111214;border-radius:8px;padding:0;overflow:hidden;width:300px;}
.dc-profile-banner{height:60px;}
.dc-profile-body{padding:12px 16px 16px;}
.dc-profile-av{margin-top:-32px;margin-bottom:12px;position:relative;display:inline-block;}
.dc-profile-av-ring{border:4px solid #111214;border-radius:50%;display:inline-block;}
.dc-profile-name{font-size:20px;font-weight:700;color:#f2f3f5;}
.dc-profile-tag{font-size:13px;color:#b5bac1;margin-bottom:12px;}
.dc-profile-sep{height:1px;background:rgba(255,255,255,0.06);margin:12px 0;}
.dc-profile-label{font-size:11px;font-weight:700;letter-spacing:.7px;color:#b5bac1;text-transform:uppercase;margin-bottom:4px;}
.dc-profile-val{font-size:14px;color:#dbdee1;}
.dc-profile-badge{display:inline-flex;align-items:center;gap:4px;background:#faa61a20;color:#faa61a;font-size:12px;font-weight:600;padding:2px 8px;border-radius:4px;}

/* Auth */
.dc-auth{min-height:100vh;background:#313338;display:flex;align-items:center;justify-content:center;
  background-image:radial-gradient(ellipse at 20% 30%,rgba(88,101,242,0.15) 0%,transparent 60%),
    radial-gradient(ellipse at 80% 70%,rgba(88,101,242,0.08) 0%,transparent 50%);}
.dc-auth-card{background:#313338;border:1px solid rgba(255,255,255,0.06);border-radius:5px;
  padding:32px;width:100%;max-width:480px;text-align:center;
  box-shadow:0 8px 16px rgba(0,0,0,0.5);}
.dc-auth-title{font-size:24px;font-weight:700;color:#f2f3f5;margin-bottom:8px;}
.dc-auth-sub{font-size:16px;color:#b5bac1;margin-bottom:24px;}
.dc-google-btn{display:flex;align-items:center;justify-content:center;gap:10px;
  width:100%;padding:12px;background:#4e9a51;border-radius:4px;
  color:#fff;font-size:16px;font-weight:600;text-decoration:none;transition:background .15s;}
.dc-google-btn:hover{background:#43a047;}
.dc-auth-features{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:24px;text-align:left;}
.dc-feat{background:rgba(255,255,255,0.03);border-radius:4px;padding:12px;}
.dc-feat-title{font-size:13px;font-weight:600;color:#f2f3f5;margin-bottom:4px;}
.dc-feat-desc{font-size:12px;color:#8e9297;}

/* Admin panel */
.dc-admin-stat{background:#2b2d31;border-radius:8px;padding:16px;text-align:center;}
.dc-admin-stat-n{font-size:28px;font-weight:700;color:#f2f3f5;}
.dc-admin-stat-l{font-size:13px;color:#8e9297;margin-top:4px;}

/* Misc */
.dc-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:#8e9297;text-align:center;padding:40px;}
.dc-empty-icon{font-size:48px;margin-bottom:16px;opacity:.5;}
.dc-empty-title{font-size:20px;font-weight:700;color:#f2f3f5;margin-bottom:8px;}
.dc-empty-sub{font-size:16px;}

/* Extra: catch ALL button variants Streamlit might render */
button[data-testid],
[class*="stButton"] button,
[class*="ButtonContainer"] button,
[class*="stBaseButton"] {
  background:transparent!important;
  background-color:transparent!important;
  border:1px solid rgba(255,255,255,0.10)!important;
  color:#b5bac1!important;
  box-shadow:none!important;
}
[class*="stButton"] button:hover,
[class*="ButtonContainer"] button:hover {
  background:rgba(255,255,255,0.07)!important;
  background-color:rgba(255,255,255,0.07)!important;
  color:#fff!important;
}
/* Keep primary blue */
[class*="stButton"] button[kind="primary"],
[data-testid="stBaseButton-primary"] {
  background:#5865f2!important;
  background-color:#5865f2!important;
  color:#fff!important;
  border:none!important;
}
</style>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════
# AUTH PAGE
# ═══════════════════════════════════════════════════
def show_auth():
    _,col,_ = st.columns([1,1.4,1])
    with col:
        st.markdown("""<div class="dc-auth"><div class="dc-auth-card">
          <div style="font-size:48px;margin-bottom:12px">💬</div>
          <div class="dc-auth-title">Welcome to StreamLine</div>
          <div class="dc-auth-sub">Sign in or create an account to continue</div>
        </div></div>""", unsafe_allow_html=True)

        auth_tab = st.session_state.get("auth_tab", "signin")

        # Tab switcher
        tc1, tc2 = st.columns(2)
        with tc1:
            if st.button("🔑 Sign In", use_container_width=True,
                         type="primary" if auth_tab=="signin" else "secondary",
                         key="tab_signin"):
                st.session_state["auth_tab"] = "signin"; st.rerun()
        with tc2:
            if st.button("✨ Register", use_container_width=True,
                         type="primary" if auth_tab=="register" else "secondary",
                         key="tab_register"):
                st.session_state["auth_tab"] = "register"; st.rerun()

        st.markdown('<div style="height:12px"></div>', unsafe_allow_html=True)

        # ── SIGN IN ──────────────────────────────────
        if auth_tab == "signin":
            si_email = st.text_input("Email address", placeholder="you@gmail.com", key="si_email")
            si_pw    = st.text_input("Password", type="password", key="si_pw")

            if st.button("Sign In →", use_container_width=True, type="primary", key="si_submit"):
                try:
                    u = login_local(si_email, si_pw)
                    tok = create_session(u["id"])
                    st.session_state["_tok"] = tok
                    st.session_state["user"] = u
                    st.query_params[SID] = tok
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

            # Google OAuth divider + button
            url = google_url() if GID else None
            st.markdown('<div class="dc-auth-or">OR CONTINUE WITH</div>', unsafe_allow_html=True)
            if url:
                st.markdown(f'<a href="{url}" class="dc-google-btn" target="_self">'
                    '<svg width="18" height="18" viewBox="0 0 24 24" style="flex-shrink:0">'
                    '<path fill="#fff" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>'
                    '<path fill="#fff" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>'
                    '<path fill="#fff" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z"/>'
                    '<path fill="#fff" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>'
                    '</svg>Sign in with Google (Gmail)</a>', unsafe_allow_html=True)
            else:
                st.markdown('<div style="background:#ed4245;color:#fff;padding:10px 14px;border-radius:6px;font-size:13px">⚠️ Google OAuth not configured in config.json</div>', unsafe_allow_html=True)

        # ── REGISTER ─────────────────────────────────
        else:
            rg_name   = st.text_input("Display Name", placeholder="Your name", key="rg_name")
            rg_email  = st.text_input("Email", placeholder="you@gmail.com", key="rg_email")
            rg_pw     = st.text_input("Password", type="password", key="rg_pw")
            rg_pw2    = st.text_input("Confirm Password", type="password", key="rg_pw2")
            rg_avatar = st.selectbox("Avatar", AVATARS, key="rg_avatar")

            if st.button("Create Account →", use_container_width=True, type="primary", key="rg_submit"):
                if rg_pw != rg_pw2:
                    st.error("Passwords do not match.")
                else:
                    try:
                        u = register_local(rg_email, rg_name, rg_avatar, rg_pw)
                        tok = create_session(u["id"])
                        st.session_state["_tok"] = tok
                        st.session_state["user"] = u
                        st.query_params[SID] = tok
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

# ═══════════════════════════════════════════════════
# FEED RENDERER
# ═══════════════════════════════════════════════════
def render_feed(html_content, height=460):
    full = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:#313338;font-family:'Inter',system-ui,sans-serif;color:#dbdee1;overflow-x:hidden;}}
::-webkit-scrollbar{{width:4px;}} ::-webkit-scrollbar-thumb{{background:#1a1b1e;border-radius:4px;}}
.feed{{padding:0 0 8px;}}
.day{{display:flex;align-items:center;gap:12px;margin:16px 0;padding:0 16px;}}
.day::before,.day::after{{content:'';flex:1;height:1px;background:rgba(255,255,255,0.06);}}
.day-lbl{{font-size:12px;font-weight:600;color:#8e9297;white-space:nowrap;}}
.msg{{display:flex;gap:16px;padding:2px 16px;position:relative;}}
.msg:hover{{background:rgba(4,4,5,0.07);}}
.msg:hover .acts{{display:flex;}}
.msg-full{{padding-top:16px;}}
.msg-grouped{{padding-left:72px;}}
.av{{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:700;color:#fff;flex-shrink:0;}}
.av img{{width:40px;height:40px;border-radius:50%;object-fit:cover;}}
.body{{flex:1;min-width:0;}}
.hdr{{display:flex;align-items:baseline;gap:8px;margin-bottom:2px;}}
.author{{font-size:15px;font-weight:600;color:#f2f3f5;cursor:pointer;}}
.author:hover{{text-decoration:underline;}}
.ts{{font-size:12px;color:#4e5058;}}
.edited{{font-size:11px;color:#4e5058;font-style:italic;}}
.pin{{font-size:10px;color:#faa61a;background:rgba(250,166,26,.1);border-radius:3px;padding:1px 5px;}}
.text{{font-size:15px;color:#dbdee1;line-height:1.5;word-break:break-word;}}
.text code{{background:#2b2d31;border-radius:3px;padding:0 4px;font-size:13px;color:#b9befe;font-family:monospace;}}
.text a{{color:#00a8fc;text-decoration:none;}} .text a:hover{{text-decoration:underline;}}
.text strong{{color:#f2f3f5;}}
.reply-bar{{display:flex;align-items:center;gap:6px;font-size:13px;color:#8e9297;margin-bottom:4px;padding-left:8px;border-left:2px solid #4e5058;}}
.rxns{{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;}}
.rxn{{display:inline-flex;align-items:center;gap:4px;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,.1);border-radius:8px;padding:2px 8px;font-size:13px;cursor:pointer;}}
.rxn:hover{{background:rgba(255,255,255,.1);}}
.rxn-n{{font-size:12px;font-weight:600;color:#b9befe;}}
.acts{{position:absolute;right:16px;top:-12px;background:#2b2d31;border:1px solid rgba(255,255,255,.06);border-radius:4px;display:none;gap:2px;padding:4px;z-index:10;}}
.act{{width:28px;height:28px;border-radius:4px;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:15px;color:#b5bac1;}}
.act:hover{{background:#404249;color:#fff;}}
.empty{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px;gap:8px;}}
.empty-icon{{font-size:48px;opacity:.4;}}
.empty-t{{font-size:18px;font-weight:700;color:#f2f3f5;}}
.empty-s{{font-size:14px;color:#8e9297;}}
</style></head><body><div class="feed">{html_content}</div>
<script>window.scrollTo(0,document.body.scrollHeight);</script>
</body></html>"""
    _c.html(full, height=height, scrolling=True)

# ═══════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════
def show_app(user):
    heartbeat(user["id"])
    for s in get_servers(): join_server(user["id"], s["id"])

    # state
    view       = st.session_state.get("view","chat")          # chat | dm | profile | admin
    server_id  = st.session_state.get("server_id")
    channel_id = st.session_state.get("channel_id")
    dm_pid     = st.session_state.get("dm_pid")
    show_members = st.session_state.get("show_members", True)
    show_pins  = st.session_state.get("show_pins", False)

    user_servers = get_servers(user["id"])
    if not server_id and user_servers:
        server_id = user_servers[0]["id"]
        st.session_state["server_id"] = server_id

    server = next((s for s in user_servers if s["id"]==server_id), None) if server_id else None
    channels_all = get_all_channels_flat(server_id) if server_id else []
    if not channel_id and channels_all:
        channel_id = channels_all[0]["id"]
        st.session_state["channel_id"] = channel_id
    channel = next((c for c in channels_all if c["id"]==channel_id), None)
    members = get_members(server_id) if server_id else []
    total_unread = unread_total(user["id"])

    # Build layout using custom HTML + Streamlit widgets layered
    # We use 4 columns to simulate Discord's layout: rail | sidebar | main | members
    if view in ("dm",):
        col_rail, col_sidebar, col_main = st.columns([72/1440, 240/1440, 1], gap="small")
        col_members = None
    elif view in ("profile","admin"):
        col_rail, col_sidebar, col_main = st.columns([72/1440, 240/1440, 1], gap="small")
        col_members = None
    else:
        if show_members:
            col_rail, col_sidebar, col_main, col_mem = st.columns([72/1440, 240/1440, 1, 240/1440], gap="small")
            col_members = col_mem
        else:
            col_rail, col_sidebar, col_main = st.columns([72/1440, 240/1440, 1], gap="small")
            col_members = None

    # ── SERVER RAIL ─────────────────────────────────
    with col_rail:
        st.markdown('<div style="background:#1e1f22;min-height:100vh;padding:8px 0;display:flex;flex-direction:column;align-items:center;gap:2px;">', unsafe_allow_html=True)

        # DMs button
        dm_active = view=="dm"
        dm_badge = f'<div class="dc-srv-notif">{min(total_unread,9)}</div>' if total_unread>0 else ""
        dm_style = "border-radius:16px;background:#5865f2;" if dm_active else ""
        if st.button("💬", key="rail_dm", help="Direct Messages",
                     use_container_width=False):
            st.session_state["view"]="dm"; st.rerun()

        st.markdown('<div style="width:32px;height:2px;background:#3a3c42;border-radius:1px;margin:4px auto"></div>', unsafe_allow_html=True)

        for s in user_servers:
            is_active = (s["id"]==server_id and view=="chat")
            btn_style = "font-size:20px"
            if st.button(s["icon"], key=f"rail_{s['id']}", help=s["name"],
                         use_container_width=False):
                st.session_state["server_id"]=s["id"]
                st.session_state["view"]="chat"
                chans=get_all_channels_flat(s["id"])
                if chans: st.session_state["channel_id"]=chans[0]["id"]
                st.rerun()

        # Add server
        if st.button("➕", key="rail_add", help="Add a Server", use_container_width=False):
            st.session_state["view"]="create_server"; st.rerun()

        st.markdown('</div>', unsafe_allow_html=True)

    # ── CHANNEL SIDEBAR ─────────────────────────────
    with col_sidebar:
        if view == "dm":
            # DM list sidebar
            st.markdown("""<div style="background:#2b2d31;min-height:100vh;display:flex;flex-direction:column;">
              <div class="dc-dm-hdr"><span class="dc-dm-hdr-title">Direct Messages</span></div>
              <div style="flex:1;overflow-y:auto;padding:8px 0;">""", unsafe_allow_html=True)

            all_u = [u for u in get_all_users() if u["id"]!=user["id"]]
            convos = get_dm_convos(user["id"])
            seen_ids = set()

            if convos:
                st.markdown('<div class="dc-dm-section">Recent</div>', unsafe_allow_html=True)
                for cv in convos:
                    oid=cv["other_id"]; seen_ids.add(oid)
                    ub=unread_from(oid,user["id"])
                    active = dm_pid==oid
                    dot_c="#22d3a5" if cv.get("status")=="online" else "#747f8d"
                    av_h = avatar_html(cv,32,11)
                    badge = f'<span style="background:#ed4245;color:#fff;font-size:10px;font-weight:700;padding:1px 5px;border-radius:8px">{ub}</span>' if ub>0 else ""
                    st.markdown(f"""<div class="dc-dm-row {'active' if active else ''}" onclick="">
                      <div style="position:relative">{av_h}
                        <div style="position:absolute;bottom:-1px;right:-1px;width:10px;height:10px;border-radius:50%;background:{dot_c};border:2px solid #2b2d31"></div>
                      </div>
                      <div style="flex:1;min-width:0"><div class="dc-dm-name" style="{'color:#f2f3f5' if active else ''}">{cv['name']}</div></div>
                      {badge}
                    </div>""", unsafe_allow_html=True)
                    if st.button("", key=f"dmsel_{oid}", use_container_width=True,
                                 help=cv["name"]):
                        st.session_state["dm_pid"]=oid; mark_dm_read(oid,user["id"]); st.rerun()

            st.markdown('<div class="dc-dm-section">All Users</div>', unsafe_allow_html=True)
            for u in all_u:
                if u["id"] not in seen_ids:
                    dot_c="#22d3a5" if u.get("status")=="online" else "#747f8d"
                    av_h=avatar_html(u,32,11)
                    st.markdown(f"""<div class="dc-dm-row">
                      <div style="position:relative">{av_h}
                        <div style="position:absolute;bottom:-1px;right:-1px;width:10px;height:10px;border-radius:50%;background:{dot_c};border:2px solid #2b2d31"></div>
                      </div>
                      <div class="dc-dm-name">{u['name']}</div>
                    </div>""", unsafe_allow_html=True)
                    if st.button("", key=f"dmnew_{u['id']}", use_container_width=True, help=u["name"]):
                        st.session_state["dm_pid"]=u["id"]; st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)

        elif view in ("chat","pins"):
            # Channel sidebar
            banner_c = server.get("banner_color","#5865f2") if server else "#5865f2"
            sname = server["name"] if server else "No Server"
            sicon = server["icon"] if server else "💬"
            st.markdown(f"""<div style="background:#2b2d31;min-height:100vh;display:flex;flex-direction:column;">
              <div class="dc-sidebar-hdr" style="background:linear-gradient(135deg,{banner_c}33,transparent)">
                <span class="dc-sidebar-title">{sname}</span><span style="color:#8e9297;font-size:14px">▾</span>
              </div>
              <div class="dc-sidebar-body">""", unsafe_allow_html=True)

            if server_id:
                cats = get_categories(server_id)
                for cat in cats:
                    cat_chs = get_channels(server_id, cat["id"])
                    if not cat_chs: continue
                    st.markdown(f'<div class="dc-category">▸ {cat["name"]}</div>', unsafe_allow_html=True)
                    for ch in cat_chs:
                        unread = get_unread_count(user["id"], ch["id"])
                        is_active = ch["id"]==channel_id and view=="chat"
                        cls = "active" if is_active else ("unread" if unread>0 else "")
                        badge = f'<span class="dc-ch-badge">{min(unread,99)}</span>' if unread>0 and not is_active else ""
                        st.markdown(f"""<div class="dc-ch-row {cls}">
                          <span class="dc-ch-icon">#</span>
                          <span class="dc-ch-name">{ch['name']}</span>{badge}
                        </div>""", unsafe_allow_html=True)
                        if st.button("", key=f"ch_{ch['id']}", use_container_width=True, help=f"#{ch['name']}"):
                            st.session_state["channel_id"]=ch["id"]
                            st.session_state["view"]="chat"
                            st.session_state.pop("search_query",None)
                            mark_channel_read(user["id"],ch["id"])
                            st.rerun()

                # Add category/channel
                with st.expander("➕ Add"):
                    t=st.selectbox("Type",["Channel","Category"],key="addtype")
                    n=st.text_input("Name",key="addname",placeholder="new-channel")
                    if t=="Channel":
                        cat_names=[c["name"] for c in cats]
                        sel_cat=st.selectbox("Category",cat_names,key="addcat") if cats else None
                        if st.button("Create Channel",key="createch",use_container_width=True):
                            if n.strip() and sel_cat:
                                cid2=next(c["id"] for c in cats if c["name"]==sel_cat)
                                create_channel(server_id,cid2,n.strip().lower().replace(" ","-"))
                                st.rerun()
                    else:
                        if st.button("Create Category",key="createcat",use_container_width=True):
                            if n.strip(): create_category(server_id,n.strip().upper()); st.rerun()

            st.markdown('</div>', unsafe_allow_html=True)

        else:
            # Generic sidebar (profile/admin)
            st.markdown('<div style="background:#2b2d31;min-height:100vh;padding:8px 0;">', unsafe_allow_html=True)
            if view=="profile":
                st.markdown('<div style="padding:16px;font-size:16px;font-weight:700;color:#f2f3f5">⚙️ User Settings</div>', unsafe_allow_html=True)
            elif view=="admin":
                st.markdown('<div style="padding:16px;font-size:16px;font-weight:700;color:#f2f3f5">🛡️ Admin Panel</div>', unsafe_allow_html=True)
            if st.button("← Back to Chat", key="backbtn", use_container_width=True):
                st.session_state["view"]="chat"; st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        # Footer always shown in sidebar
        uc=user.get("color","#5865f2"); ui=ini(user["name"])
        uav=avatar_html(user,32,11)
        dot_c="#22d3a5"
        st.markdown(f"""<div class="dc-sidebar-footer">
          <div class="dc-footer-av">{uav}
            <div class="dc-footer-dot" style="background:{dot_c}"></div>
          </div>
          <div class="dc-footer-info">
            <div class="dc-footer-name">{user['name']}</div>
            <div class="dc-footer-tag">{user['email'][:20]}{'…' if len(user['email'])>20 else ''}</div>
          </div>
          <div class="dc-footer-icons">""", unsafe_allow_html=True)

        fi1,fi2,fi3 = st.columns(3)
        with fi1:
            if st.button("⚙️",key="f_profile",help="Profile"):
                st.session_state["view"]="profile"; st.rerun()
        with fi2:
            if user.get("is_admin"):
                if st.button("🛡️",key="f_admin",help="Admin"):
                    st.session_state["view"]="admin"; st.rerun()
        with fi3:
            if st.button("⏻",key="f_out",help="Sign Out"):
                del_session(gtok())
                for k in list(st.session_state.keys()): del st.session_state[k]
                st.query_params.clear(); st.rerun()

        st.markdown('</div></div>', unsafe_allow_html=True)

    # ── MAIN CONTENT ────────────────────────────────
    with col_main:
        if view == "profile":
            show_profile_page(user)
        elif view == "admin":
            show_admin_page(user)
        elif view == "dm":
            show_dm_page(user, dm_pid)
        elif view == "create_server":
            show_create_server(user)
        else:
            show_chat_page(user, server, channel, members, show_pins)

    # ── MEMBERS PANEL ───────────────────────────────
    if col_members and view=="chat":
        with col_members:
            show_members_panel(members, user)


# ═══════════════════════════════════════════════════
# CHAT PAGE
# ═══════════════════════════════════════════════════
def show_chat_page(user, server, channel, members, show_pins):
    if not server:
        st.markdown('<div class="dc-empty" style="min-height:100vh"><div class="dc-empty-icon">🌍</div><div class="dc-empty-title">No servers yet</div><div class="dc-empty-sub">Create or join a server to get started</div></div>', unsafe_allow_html=True)
        return
    if not channel:
        st.markdown('<div class="dc-empty" style="min-height:100vh"><div class="dc-empty-icon">📢</div><div class="dc-empty-title">No channels</div><div class="dc-empty-sub">Create a channel to start chatting</div></div>', unsafe_allow_html=True)
        return

    # Topbar
    online_n = len([m for m in members if m.get("status")=="online"])
    topic = channel.get("topic","") or ""
    show_m = st.session_state.get("show_members", True)
    pinned = get_pinned(channel["id"])
    pin_cnt = len(pinned)

    tc1,tc2,tc3,tc4,tc5,tc6 = st.columns([1,3,1,1,1,1])
    with tc1:
        st.markdown(f'<div class="dc-topbar-icon">#</div>', unsafe_allow_html=True)
    with tc2:
        st.markdown(f'<div style="display:flex;align-items:center;gap:8px;height:48px"><span style="font-size:16px;font-weight:700;color:#f2f3f5"># {channel["name"]}</span><span style="font-size:14px;color:#8e9297;margin-left:4px">{topic}</span></div>', unsafe_allow_html=True)
    with tc3:
        if pin_cnt > 0:
            if st.button(f"📌 {pin_cnt}", key="show_pins_btn", help="Pinned Messages"):
                st.session_state["show_pins"] = not show_pins; st.rerun()
    with tc4:
        if st.button(f"👥 {online_n}", key="toggle_members", help="Toggle Members"):
            st.session_state["show_members"] = not show_m; st.rerun()
    with tc5:
        sq = st.text_input("🔍", placeholder="Search…", label_visibility="collapsed",
                            value=st.session_state.get("search_query",""), key="srch")
        if sq != st.session_state.get("search_query",""):
            st.session_state["search_query"]=sq; st.rerun()
    with tc6:
        pass

    st.markdown('<hr style="border:none;border-top:1px solid rgba(0,0,0,.3);margin:0">', unsafe_allow_html=True)

    # Pinned panel
    if show_pins and pinned:
        with st.expander(f"📌 {pin_cnt} Pinned Messages", expanded=True):
            for p in pinned:
                st.markdown(f'<div style="background:#2b2d31;border-radius:4px;padding:10px 14px;margin:4px 0;border-left:3px solid #faa61a"><div style="font-size:11px;color:#faa61a;font-weight:700;margin-bottom:4px">{p["username"]}</div><div style="font-size:14px;color:#dbdee1">{p["content"][:120]}</div></div>', unsafe_allow_html=True)

    # Welcome banner
    search = st.session_state.get("search_query","")
    if not search:
        stats = get_server_stats(server["id"])
        st.markdown(f"""<div class="dc-welcome">
          <div class="dc-welcome-av">#</div>
          <div class="dc-welcome-title">Welcome to #{channel['name']}!</div>
          <div class="dc-welcome-sub">{topic or 'This is the start of the channel.'}<br>
            <span style="font-size:14px;color:#4e5058">👥 {stats['members']} members · 💬 {stats['messages']} messages</span>
          </div>
        </div>
        <div style="height:1px;background:rgba(255,255,255,0.04);margin:0 16px 8px"></div>""",
            unsafe_allow_html=True)

    # Messages
    messages = get_messages(channel["id"], search=search)
    rxns = get_reactions(channel["id"])
    feed = ""

    if not messages:
        feed = '<div class="empty"><div class="empty-icon">💬</div><div class="empty-t">No messages yet</div><div class="empty-s">Be the first to say something!</div></div>'
    else:
        prev_uid=None; prev_dt=None
        for i,msg in enumerate(messages):
            mid=msg["id"]; color=msg.get("color","#5865f2")
            uname=msg["username"]; t=fmt(msg["created"]); full_t=fmt_full(msg["created"])
            content=mdparse(msg["content"]); edited=msg.get("edited",0); pinned_m=msg.get("pinned",0)
            pic_url=msg.get("avatar_url","")
            try:
                cdt=datetime.strptime(msg["created"][:19],"%Y-%m-%d %H:%M:%S")
                gap=(prev_dt is None) or (cdt-prev_dt>timedelta(minutes=7))
            except: gap=True
            grouped=(msg["user_id"]==prev_uid) and not gap

            # Day separator
            if i==0:
                today=datetime.utcnow().strftime("%d %b %Y")
                feed+=f'<div class="day"><span class="day-lbl">Today — {today}</span></div>'

            edit_b=f'<span class="edited">(edited)</span>' if edited else ''
            pin_b=f'<span class="pin">📌</span>' if pinned_m else ''
            rxns_h=""
            if mid in rxns:
                rxns_h='<div class="rxns">'+"".join(f'<span class="rxn">{e} <span class="rxn-n">{cnt}</span></span>' for e,cnt in rxns[mid].items())+'</div>'

            if not grouped:
                if pic_url:
                    av_h=f'<div class="av"><img src="{pic_url}"></div>'
                else:
                    av_h=f'<div class="av" style="background:{color}">{ini(uname)}</div>'
                feed+=f'<div class="msg msg-full" id="m{mid}">{av_h}<div class="body"><div class="hdr"><span class="author">{uname}</span><span class="ts" title="{full_t}">{t}</span>{pin_b}{edit_b}</div><div class="text">{content}</div>{rxns_h}</div></div>'
            else:
                feed+=f'<div class="msg msg-grouped" id="m{mid}"><div class="body"><div class="text" style="margin-left:0">{content}</div>{rxns_h}</div></div>'

            try: prev_dt=datetime.strptime(msg["created"][:19],"%Y-%m-%d %H:%M:%S")
            except: prev_dt=None
            prev_uid=msg["user_id"]

    render_feed(feed, 440)

    # Typing indicator
    typers = get_typing(channel["id"], user["id"])
    if typers:
        names = ", ".join(typers[:3])
        suffix = " are typing…" if len(typers)>1 else " is typing…"
        st.markdown(f'<div class="dc-typing"><span style="font-size:12px">⌨️ <strong>{names}</strong>{suffix}</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div style="height:20px"></div>', unsafe_allow_html=True)

    # Message actions (react/edit/delete/pin)
    if messages:
        with st.expander("⚡ Message Actions"):
            a1,a2,a3 = st.columns([3,2,2])
            with a1:
                recent=messages[-20:]
                opts=[str(m["id"]) for m in recent]
                lbls=[f"#{m['id']} {m['username'][:8]}: {m['content'][:25]}…" for m in recent]
                sel_mid=st.selectbox("Message",opts,format_func=lambda x:lbls[opts.index(x)],key="act_mid")
            with a2:
                em=st.selectbox("Emoji",["👍","❤️","😂","🔥","🎉","😮","💯","✅","😢","🤔"],key="act_em")
            with a3:
                if st.button("React",key="do_react",use_container_width=True):
                    add_reaction(int(sel_mid),user["id"],em); st.rerun()

            own_msgs=[m for m in messages if m["user_id"]==user["id"]]
            admin_all=messages if user.get("is_admin") else []
            editable = own_msgs
            deletable = messages if user.get("is_admin") else own_msgs
            if deletable:
                st.markdown("---")
                b1,b2,b3=st.columns([3,1,1])
                with b1:
                    dops=[str(m["id"]) for m in deletable]
                    dlbls=[f"#{m['id']} {m['username'][:8]}: {m['content'][:25]}…" for m in deletable]
                    del_mid=st.selectbox("Message",dops,format_func=lambda x:dlbls[dops.index(x)],key="del_mid")
                with b2:
                    if st.button("🗑️ Delete",key="do_del",use_container_width=True):
                        delete_message(int(del_mid),user["id"],user.get("is_admin",False)); st.rerun()
                with b3:
                    if st.button("📌 Pin",key="do_pin",use_container_width=True):
                        pin_message(int(del_mid)); st.rerun()
            if editable:
                st.markdown("---")
                eops=[str(m["id"]) for m in editable]
                elbls=[f"#{m['id']}: {m['content'][:30]}…" for m in editable]
                e_mid=st.selectbox("Your message",eops,format_func=lambda x:elbls[eops.index(x)],key="edit_mid")
                orig=next((m["content"] for m in editable if str(m["id"])==e_mid),"")
                nc=st.text_input("New content",value=orig,key="edit_content")
                if st.button("✏️ Save Edit",key="do_edit",use_container_width=True):
                    if nc.strip(): edit_message(int(e_mid),user["id"],nc.strip()); st.rerun()

    # Composer
    st.markdown(f'<div style="padding:0 16px 4px;font-size:12px;color:#8e9297">Sending to <strong style="color:#f2f3f5">#{channel["name"] if channel else "..."}</strong></div>', unsafe_allow_html=True)
    quick=["😊","👍","🔥","❤️","🎉","😂","🤔","💯","🙏","✨","😎","🚀"]
    st.markdown("""<style>
    .eq-row{display:flex;gap:4px;margin-bottom:4px;}
    .eq-btn{background:transparent!important;border:1px solid rgba(255,255,255,0.12);border-radius:6px;
            font-size:18px;cursor:pointer;padding:4px 8px;transition:background .15s;line-height:1.4;}
    .eq-btn:hover{background:rgba(255,255,255,0.1)!important;border-color:rgba(255,255,255,0.25);}
    </style>""", unsafe_allow_html=True)
    eq_cols = st.columns(len(quick))
    for i,e in enumerate(quick):
        with eq_cols[i]:
            if st.button(e, key=f"eq{i}", help=e):
                cur=st.session_state.get("miv",""); st.session_state["miv"]=cur+e

    # JS override: strip blue background from emoji quick-buttons at runtime
    st.markdown("""
    <script>
    (function(){
      function fixEmojiButtons(){
        document.querySelectorAll('button').forEach(function(btn){
          var t = btn.innerText ? btn.innerText.trim() : '';
          // emoji buttons have 1-2 chars (the emoji itself)
          if([...t].length <= 2 && t.length > 0 && t !== '+'){
            btn.style.setProperty('background','transparent','important');
            btn.style.setProperty('background-color','transparent','important');
            btn.style.setProperty('border','1px solid rgba(255,255,255,0.12)','important');
            btn.style.setProperty('box-shadow','none','important');
            btn.style.setProperty('color','unset','important');
          }
        });
      }
      var mo = new MutationObserver(fixEmojiButtons);
      mo.observe(document.body, {childList:true, subtree:true});
      fixEmojiButtons();
    })();
    </script>
    """, unsafe_allow_html=True)


    cc1,cc2=st.columns([6,1])
    with cc1:
        dv=st.session_state.pop("miv","")
        msg_txt=st.text_input("msg",placeholder=f"Message #{channel['name'] if channel else ''}",
                               label_visibility="collapsed",key="msgin",value=dv)
        if msg_txt: set_typing(user["id"], channel["id"])
    with cc2:
        send=st.button("Send",type="primary",use_container_width=True,key="sendbtn")
    if send and msg_txt.strip() and channel:
        post_message(channel["id"],user["id"],msg_txt.strip())
        mark_channel_read(user["id"],channel["id"])
        st.rerun()

    if st.session_state.get("auto_refresh",True):
        time.sleep(2); st.rerun()


# ═══════════════════════════════════════════════════
# MEMBERS PANEL
# ═══════════════════════════════════════════════════
def show_members_panel(members, user):
    admins=[m for m in members if m.get("role")=="admin" or m.get("is_admin")]
    regulars=[m for m in members if not (m.get("role")=="admin" or m.get("is_admin"))]
    online_r=[m for m in regulars if m.get("status")=="online"]
    offline_r=[m for m in regulars if m.get("status")!="online"]

    st.markdown('<div style="background:#2b2d31;min-height:100vh;overflow-y:auto;padding:16px 0;">', unsafe_allow_html=True)

    if admins:
        st.markdown(f'<div class="dc-members-section">Admin — {len(admins)}</div>', unsafe_allow_html=True)
        for m in admins:
            dot="#22d3a5" if m.get("status")=="online" else "#747f8d"
            av_h=avatar_html(m,32,11)
            badge='<div class="dc-member-badge">⭐ Admin</div>' if m.get("is_admin") or m.get("role")=="admin" else ""
            st.markdown(f"""<div class="dc-member-row">
              <div class="dc-member-av">{av_h}
                <div class="dc-member-dot" style="background:{dot};border-color:#2b2d31"></div>
              </div>
              <div class="dc-member-info">
                <div class="dc-member-name" style="color:#faa61a">{m['name']}</div>
                {badge}
              </div>
            </div>""", unsafe_allow_html=True)

    if online_r:
        st.markdown(f'<div class="dc-members-section">Online — {len(online_r)}</div>', unsafe_allow_html=True)
        for m in online_r:
            av_h=avatar_html(m,32,11)
            st.markdown(f"""<div class="dc-member-row">
              <div class="dc-member-av">{av_h}
                <div class="dc-member-dot" style="background:#22d3a5;border-color:#2b2d31"></div>
              </div>
              <div class="dc-member-info"><div class="dc-member-name">{m['name']}</div></div>
            </div>""", unsafe_allow_html=True)

    if offline_r:
        st.markdown(f'<div class="dc-members-section">Offline — {len(offline_r)}</div>', unsafe_allow_html=True)
        for m in offline_r:
            av_h=avatar_html(m,32,11)
            st.markdown(f"""<div class="dc-member-row">
              <div class="dc-member-av" style="opacity:.5">{av_h}
                <div class="dc-member-dot" style="background:#747f8d;border-color:#2b2d31"></div>
              </div>
              <div class="dc-member-info"><div class="dc-member-name" style="opacity:.6">{m['name']}</div></div>
            </div>""", unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════
# DM PAGE
# ═══════════════════════════════════════════════════
def show_dm_page(user, pid):
    if not pid:
        st.markdown('<div class="dc-empty" style="min-height:100vh"><div class="dc-empty-icon">💬</div><div class="dc-empty-title">Your messages</div><div class="dc-empty-sub">Select a conversation from the sidebar or start a new one</div></div>', unsafe_allow_html=True)
        return

    partner=get_user(pid)
    if not partner: st.error("User not found."); return

    pc=partner.get("color","#5865f2"); pi=ini(partner["name"])
    dot_c="#22d3a5" if partner.get("status")=="online" else "#747f8d"
    online_t="● Online" if partner.get("status")=="online" else "● Offline"
    online_col="#22d3a5" if partner.get("status")=="online" else "#747f8d"
    pav=avatar_html(partner,40,14)

    st.markdown(f"""<div style="background:#313338;border-bottom:1px solid rgba(0,0,0,.3);height:48px;display:flex;align-items:center;padding:0 16px;gap:12px;">
      <div style="position:relative">{pav}
        <div style="position:absolute;bottom:-1px;right:-1px;width:12px;height:12px;border-radius:50%;background:{dot_c};border:3px solid #313338"></div>
      </div>
      <div>
        <div style="font-size:16px;font-weight:700;color:#f2f3f5">{partner['name']}</div>
        <div style="font-size:12px;color:{online_col}">{online_t}</div>
      </div>
    </div>""", unsafe_allow_html=True)

    msgs=get_dms(user["id"],pid)
    feed=""
    if not msgs:
        mav=avatar_html(partner,68,24)
        feed=f'<div class="empty"><div style="margin-bottom:16px">{mav}</div><div class="empty-t">Start a conversation with {partner["name"]}</div><div class="empty-s">Your messages are private</div></div>'
    else:
        prev=None
        feed+='<div class="day"><span class="day-lbl">Today</span></div>'
        for m in msgs:
            mine=m["from_user"]==user["id"]
            sname=user["name"] if mine else partner["name"]
            sc=user.get("color","#5865f2") if mine else pc
            spic=user.get("avatar_url","") if mine else partner.get("avatar_url","")
            t=fmt(m["created"]); full_t=fmt_full(m["created"])
            content=mdparse(m["content"])
            grouped=prev==m["from_user"]
            if not grouped:
                if spic:
                    av_h=f'<div class="av"><img src="{spic}"></div>'
                else:
                    av_h=f'<div class="av" style="background:{sc}">{ini(sname)}</div>'
                feed+=f'<div class="msg msg-full">{av_h}<div class="body"><div class="hdr"><span class="author">{sname}</span><span class="ts" title="{full_t}">{t}</span></div><div class="text">{content}</div></div></div>'
            else:
                feed+=f'<div class="msg msg-grouped"><div class="body"><div class="text">{content}</div></div></div>'
            prev=m["from_user"]

    render_feed(feed, 420)
    st.markdown('<div style="height:8px"></div>', unsafe_allow_html=True)

    dc1,dc2=st.columns([6,1])
    with dc1:
        dm_txt=st.text_input("dm",placeholder=f"Message {partner['name']}",label_visibility="collapsed",key="dmin")
    with dc2:
        if st.button("Send",type="primary",use_container_width=True,key="dmsend"):
            if dm_txt.strip(): send_dm(user["id"],pid,dm_txt.strip()); st.rerun()


# ═══════════════════════════════════════════════════
# PROFILE PAGE
# ═══════════════════════════════════════════════════
def show_profile_page(user):
    color=user.get("color","#5865f2"); ui=ini(user["name"])
    uav=avatar_html(user,80,28)
    badge='<div class="dc-profile-badge">⭐ Admin</div>' if user.get("is_admin") else ""

    st.markdown(f"""<div style="padding:40px;max-width:700px;background:#313338;min-height:100vh">
      <div style="font-size:20px;font-weight:700;color:#f2f3f5;margin-bottom:24px">⚙️ My Account</div>
      <div class="dc-profile-popup" style="width:100%;margin-bottom:24px">
        <div class="dc-profile-banner" style="background:linear-gradient(135deg,{color},{color}88)"></div>
        <div class="dc-profile-body">
          <div class="dc-profile-av">
            <div class="dc-profile-av-ring">{uav}</div>
          </div>
          <div class="dc-profile-name">{user['name']} {badge}</div>
          <div class="dc-profile-tag">{user['email']}</div>
          <div class="dc-profile-sep"></div>
          <div class="dc-profile-label">Bio</div>
          <div class="dc-profile-val">{user.get('bio','') or 'No bio set.'}</div>
          <div class="dc-profile-sep"></div>
          <div class="dc-profile-label">Member Since</div>
          <div class="dc-profile-val">{user.get('created','')[:10]}</div>
          <div class="dc-profile-sep"></div>
          <div class="dc-profile-label">Login Provider</div>
          <div class="dc-profile-val">{'🌐 Google' if user.get('provider')=='google' else '🔑 Local'}</div>
        </div>
      </div>""", unsafe_allow_html=True)

    st.markdown("**Edit Profile**")
    n=st.text_input("Display Name",value=user["name"],key="pn")
    av=st.selectbox("Avatar Emoji",AVATARS,
                    index=AVATARS.index(user["avatar"]) if user.get("avatar") in AVATARS else 0,key="pav")
    bio=st.text_area("About Me",value=user.get("bio",""),max_chars=190,key="pbio",
                      placeholder="Tell us something about yourself…")
    if st.button("💾 Save Changes",key="psave",use_container_width=True):
        if n.strip():
            update_profile(user["id"],n.strip(),av,bio)
            st.session_state["user"]=get_user(user["id"])
            st.success("✅ Profile updated!")
            time.sleep(0.4); st.rerun()
        else: st.error("Name cannot be empty.")

    if user.get("provider") == "local":
        st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.06);margin:20px 0">', unsafe_allow_html=True)
        st.markdown("**Change Password**")
        old_pw  = st.text_input("Current Password", type="password", key="cp_old")
        new_pw  = st.text_input("New Password", type="password", key="cp_new")
        new_pw2 = st.text_input("Confirm New Password", type="password", key="cp_new2")
        if st.button("🔒 Update Password", key="cp_save", use_container_width=True):
            if new_pw != new_pw2:
                st.error("New passwords do not match.")
            else:
                try:
                    change_password(user["id"], old_pw, new_pw)
                    st.success("✅ Password updated!")
                except ValueError as e:
                    st.error(str(e))

    st.markdown("</div>", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════
# ADMIN PAGE
# ═══════════════════════════════════════════════════
def show_admin_page(user):
    if not user.get("is_admin"):
        st.error("⛔ Access denied."); return

    st.markdown('<div style="padding:32px;background:#313338;min-height:100vh">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:24px;font-weight:700;color:#f2f3f5;margin-bottom:24px">🛡️ Admin Panel</div>', unsafe_allow_html=True)

    all_u=get_all_users()
    all_s=get_servers()
    with db() as c:
        total_msgs=c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        total_dms=c.execute("SELECT COUNT(*) FROM direct_messages").fetchone()[0]

    c1,c2,c3,c4=st.columns(4)
    for col,(n,l) in zip([c1,c2,c3,c4],[
        (len(all_u),"Users"),(len(all_s),"Servers"),(total_msgs,"Messages"),(total_dms,"DMs")]):
        with col:
            st.markdown(f'<div class="dc-admin-stat"><div class="dc-admin-stat-n">{n}</div><div class="dc-admin-stat-l">{l}</div></div>', unsafe_allow_html=True)

    st.markdown('<div style="height:24px"></div>', unsafe_allow_html=True)
    tab_u, tab_s, tab_m = st.tabs(["👥 Users", "🌍 Servers", "💬 Recent Messages"])

    with tab_u:
        for u in all_u:
            uc1,uc2,uc3,uc4=st.columns([3,2,2,2])
            with uc1: st.markdown(f'<div style="color:#f2f3f5;font-weight:600">{u["name"]}</div><div style="color:#8e9297;font-size:12px">{u["email"]}</div>', unsafe_allow_html=True)
            with uc2: st.markdown(f'<div style="color:{"#faa61a" if u.get("is_admin") else "#8e9297"};font-size:13px">{"⭐ Admin" if u.get("is_admin") else "Member"}</div>', unsafe_allow_html=True)
            with uc3: st.markdown(f'<div style="color:{"#22d3a5" if u.get("status")=="online" else "#4e5058"};font-size:13px">{"● Online" if u.get("status")=="online" else "○ Offline"}</div>', unsafe_allow_html=True)
            with uc4:
                if u["id"] != user["id"]:
                    if st.button("Toggle Admin",key=f"tadm_{u['id']}", use_container_width=True):
                        with db() as c2:
                            new_val=0 if u.get("is_admin") else 1
                            c2.execute("UPDATE users SET is_admin=? WHERE id=?",(new_val,u["id"]))
                        st.rerun()
            st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.04);margin:4px 0">', unsafe_allow_html=True)

    with tab_s:
        for s in all_s:
            stats=get_server_stats(s["id"])
            sc1,sc2=st.columns([3,2])
            with sc1: st.markdown(f'<div style="color:#f2f3f5;font-weight:600">{s["icon"]} {s["name"]}</div><div style="color:#8e9297;font-size:12px">{s.get("description","")}</div>', unsafe_allow_html=True)
            with sc2: st.markdown(f'<div style="color:#8e9297;font-size:13px">👥 {stats["members"]} · 💬 {stats["messages"]} · 📢 {stats["channels"]}</div>', unsafe_allow_html=True)
            st.markdown('<hr style="border:none;border-top:1px solid rgba(255,255,255,0.04);margin:4px 0">', unsafe_allow_html=True)

    with tab_m:
        with db() as c:
            recent_msgs=c.execute("""SELECT m.content,m.created,u.name,ch.name as cname
                FROM messages m JOIN users u ON u.id=m.user_id
                JOIN channels ch ON ch.id=m.channel_id
                ORDER BY m.id DESC LIMIT 50""").fetchall()
        for rm in recent_msgs:
            st.markdown(f'<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04)"><span style="color:#5865f2;font-weight:600">#{rm["cname"]}</span> <span style="color:#f2f3f5">{rm["name"]}</span> <span style="color:#4e5058;font-size:12px">{fmt(rm["created"])}</span><br><span style="color:#dbdee1;font-size:14px">{rm["content"][:100]}</span></div>', unsafe_allow_html=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════
# CREATE SERVER PAGE
# ═══════════════════════════════════════════════════
def show_create_server(user):
    st.markdown('<div style="padding:40px;background:#313338;min-height:100vh;max-width:500px">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:24px;font-weight:700;color:#f2f3f5;text-align:center;margin-bottom:8px">Create Your Server</div>', unsafe_allow_html=True)
    st.markdown('<div style="font-size:16px;color:#8e9297;text-align:center;margin-bottom:24px">Give your server a personality with a name and an icon.</div>', unsafe_allow_html=True)

    name=st.text_input("SERVER NAME",placeholder="My Awesome Server",key="csname")
    icon=st.selectbox("SERVER ICON",["💬","🎮","🎨","🚀","🌍","🎵","📚","🏆","🔬","🎭","🌊","⚡","🎪","🦁","🐉"],key="csicon")
    desc=st.text_input("DESCRIPTION",placeholder="What's this server about?",key="csdesc")
    color=st.selectbox("ACCENT COLOR",["#5865f2","#57f287","#fee75c","#eb459e","#ed4245","#e67e22"],key="cscolor")

    c1,c2=st.columns(2)
    with c1:
        if st.button("Cancel",key="cs_cancel",use_container_width=True):
            st.session_state["view"]="chat"; st.rerun()
    with c2:
        if st.button("Create Server",key="cs_create",use_container_width=True):
            if name.strip():
                create_server(name.strip(),icon,user["id"],desc.strip(),color)
                new_s=get_servers(user["id"])
                if new_s:
                    st.session_state["server_id"]=new_s[-1]["id"]
                    st.session_state["view"]="chat"
                    chs=get_all_channels_flat(new_s[-1]["id"])
                    if chs: st.session_state["channel_id"]=chs[0]["id"]
                st.rerun()
            else: st.error("Server name is required.")

    st.markdown('</div>', unsafe_allow_html=True)


# ═══════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════
def main():
    init_db()
    css()
    params=st.query_params

    if "user" not in st.session_state:
        tok=st.session_state.get("_tok") or params.get(SID)
        if tok:
            u=validate_session(tok)
            if u:
                st.session_state["_tok"]=tok
                st.session_state["user"]=u

    if "code" in params and "user" not in st.session_state:
        try:
            u=google_cb(params["code"])
            tok=create_session(u["id"])
            st.session_state["_tok"]=tok
            st.session_state["user"]=u
            st.query_params.clear()
            st.query_params[SID]=tok
            st.rerun()
        except Exception as e:
            st.error(f"Google auth failed: {e}")
            st.query_params.clear()

    if "user" not in st.session_state:
        show_auth()
    else:
        if SID not in params:
            st.query_params[SID]=st.session_state.get("_tok","")
        if params.get("page")=="login":
            st.query_params.pop("page",None); st.rerun()
        u=get_user(st.session_state["user"]["id"])
        if u:
            st.session_state["user"]=u
        # Enforce admin
        if u and u.get("email")==ADMIN_EMAIL:
            with db() as c: c.execute("UPDATE users SET is_admin=1 WHERE email=?",(ADMIN_EMAIL,))
            st.session_state["user"]["is_admin"]=1
        show_app(st.session_state["user"])

if __name__=="__main__":
    main()
