import streamlit as st
import pandas as pd
import sqlite3
import stripe
import hashlib

# ---------- CONFIG ----------
st.set_page_config(page_title="TripSplit AI", page_icon="🌍", layout="wide")

STRIPE_KEY = "sk_test_XXXX"
stripe.api_key = STRIPE_KEY

# ---------- STYLE ----------
st.markdown("""
<style>
.main {background-color:#0f172a;color:white;}
h1,h2,h3 {color:#38bdf8;}
.stButton>button {background:#38bdf8;color:black;border-radius:10px;}
.stMetric {background:#1e293b;padding:15px;border-radius:12px;}
</style>
""", unsafe_allow_html=True)

# ---------- DB ----------
conn = sqlite3.connect("travel.db", check_same_thread=False)
c = conn.cursor()

c.execute("""CREATE TABLE IF NOT EXISTS users(
    username TEXT PRIMARY KEY,
    password TEXT
)""")

c.execute("""CREATE TABLE IF NOT EXISTS trips(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT,
    activity TEXT,
    base_cost REAL,
    class TEXT,
    paid_by TEXT
)""")

conn.commit()

# ---------- AUTH ----------
def hash_password(p):
    return hashlib.sha256(p.encode()).hexdigest()

# default users
c.execute("INSERT OR IGNORE INTO users VALUES (?,?)", ("ali", hash_password("1234")))
c.execute("INSERT OR IGNORE INTO users VALUES (?,?)", ("sara", hash_password("abcd")))
conn.commit()

if "user" not in st.session_state:
    st.session_state.user = None

def login():
    st.title("🔐 Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")

    if st.button("Login"):
        c.execute("SELECT * FROM users WHERE username=? AND password=?",
                  (u, hash_password(p)))
        if c.fetchone():
            st.session_state.user = u
            st.success("Welcome 🚀")
        else:
            st.error("Wrong credentials")

if not st.session_state.user:
    login()
    st.stop()

# ---------- SIDEBAR ----------
st.sidebar.title("⚙️ Settings")
st.sidebar.write("👤", st.session_state.user)

currency = st.sidebar.selectbox("Currency", ["DH", "$", "€"])
extra_fee = st.sidebar.slider("Extra %", 0, 20, 5) / 100
destination = st.sidebar.text_input("🌆 Destination", "Casablanca")

if st.sidebar.button("Logout"):
    st.session_state.user = None
    st.rerun()

# ---------- CONSTANTS ----------
travelers = ['Ali 🧳', 'Sara 🌴', 'Youssef 📸', 'Lina 🏝️']

CLASS = {
    "Economy ✈️":1.0,
    "Business 💼":1.5,
    "First 👑":2.2
}

# ---------- DATA ----------
def load():
    c.execute("SELECT activity,base_cost,class,paid_by FROM trips WHERE user=?",
              (st.session_state.user,))
    return pd.DataFrame(c.fetchall(), columns=['activity','base_cost','class','paid_by'])

def save(df):
    c.execute("DELETE FROM trips WHERE user=?", (st.session_state.user,))
    for _,r in df.iterrows():
        c.execute("INSERT INTO trips(user,activity,base_cost,class,paid_by) VALUES (?,?,?,?,?)",
                  (st.session_state.user,r['activity'],r['base_cost'],r['class'],r['paid_by']))
    conn.commit()

df = load()

# ---------- HEADER ----------
st.title("💸 TripSplit AI")
st.caption("Plan • Split • Pay • Smart Budget")

# ---------- MAP ----------
st.subheader(f"🗺️ Destination: {destination}")
st.map(pd.DataFrame({'lat':[33.57],'lon':[-7.58]}))

# ---------- EDITOR ----------
st.subheader("🧾 Activities")

df = st.data_editor(
    df,
    column_config={
        "activity":"Activity",
        "base_cost":st.column_config.NumberColumn(format=f"{currency}%.2f"),
        "class":st.column_config.SelectboxColumn(options=list(CLASS.keys())),
        "paid_by":st.column_config.SelectboxColumn(options=travelers)
    },
    num_rows="dynamic",
    use_container_width=True,
    hide_index=True
)

if st.button("💾 Save"):
    save(df)
    st.success("Saved!")

# ---------- AI ----------
def predict(df):
    if df.empty: return 0
    return df['base_cost'].mean()*len(df)*1.2

pred = predict(df)
st.info(f"🤖 Expected budget: {currency}{pred:.2f}")

# ---------- CALCULATE ----------
if st.button("💰 Calculate"):
    df = df.dropna()

    df['final'] = df.apply(
        lambda r: r['base_cost']*CLASS[r['class']]*(1+extra_fee),
        axis=1
    )

    total = df['final'].sum()
    split = total/len(travelers)

    paid = df.groupby('paid_by')['final'].sum().to_dict()

    col1,col2,col3 = st.columns(3)
    col1.metric("Total", f"{currency}{total:.2f}")
    col2.metric("Per Person", f"{currency}{split:.2f}")
    col3.metric("Activities", len(df))

    balances={}
    for p in travelers:
        balances[p]=paid.get(p,0)-split

    st.subheader("💳 Payments")

    creditors={p:b for p,b in balances.items() if b>0}
    debtors={p:-b for p,b in balances.items() if b<0}

    # ---------- STRIPE ----------
    def pay(amount):
        s=stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data':{
                    'currency':'usd',
                    'product_data':{'name':'Trip Payment'},
                    'unit_amount':int(amount*100)
                },
                'quantity':1
            }],
            mode='payment',
            success_url='https://example.com',
            cancel_url='https://example.com'
        )
        return s.url

    for d,debt in debtors.items():
        for c_,credit in creditors.items():
            if debt<=0: break
            if credit<=0: continue

            pay_amount=min(debt,credit)

            st.markdown(f"""
            <div style="background:#1e293b;padding:10px;border-radius:10px;margin:5px;">
            {d} ➡️ {c_} : {currency}{pay_amount:.2f}
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"Pay {pay_amount:.2f} ({d})"):
                url=pay(pay_amount)
                st.markdown(f"[👉 Pay here]({url})")

            debt-=pay_amount
            creditors[c_]-=pay_amount

    st.toast("✅ الحساب كامل!")