# 💬 StreamLine PRO v2.0 — Discord Clone with Streamlit

A fully-featured Discord-like chat app built with **Streamlit + SQLite**.

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the app
```bash
streamlit run app.py
```

Open http://sadox1.streamlit.app in your browser.

---

## 🔑 Demo Accounts (no setup needed)
| Email | Password |
|-------|----------|
| admin@example.com | admin123 |
| alice@example.com | alice123 |
| bob@example.com   | bob123   |

---

## ✨ New Features in v2.0

### 🐛 Bug Fixes
- **Fixed**: `oauth_flow` not cleared after login, causing stale OAuth state
- **Fixed**: `channel_idx` out-of-bounds crash when server has no channels
- **Fixed**: Avatar initials crash on single-word names
- **Fixed**: Google OAuth callback error not clearing query params, looping forever
- **Fixed**: `get_conn()` not using `check_same_thread=False` properly in all paths
- **Fixed**: Message grouping based on user_id (not name) — prevents cross-user grouping bugs
- **Fixed**: Empty email/password silently failing instead of showing an error
- **Fixed**: Server creation not setting `channel_idx` properly
- **Fixed**: Register form not validating email format
- **Fixed**: User session not refreshed from DB after profile changes

### 🆕 New Features
- **📝 Message Editing** — Edit or delete your own messages
- **📌 Pinned Messages** — Pin important messages, view in topbar panel
- **😂 Reactions** — React to any message with emoji, with reaction counts
- **💬 Direct Messages** — Private DMs between any two users
- **👤 User Profiles** — Bio, status, avatar, edit profile, change password
- **🌍 Server Discovery** — Browse and join all available servers
- **🔍 Message Search** — Search within any channel
- **📊 Server Stats** — Live member/message/channel counts
- **👥 Member Roles** — Admin vs member display in sidebar
- **🔄 Auto-refresh Toggle** — Turn off the 3s auto-refresh when not needed
- **⚡ Quick Emoji Bar** — One-click emoji insert into message composer
- **📝 Channel Topics** — Each channel can have a description/topic
- **🌐 Server Descriptions** — Servers have descriptions shown in discovery
- **📅 Smart Timestamps** — "Today at 14:32", "Yesterday at 09:00", or full date
- **📖 Markdown Rendering** — Bold, italic, inline code, links in messages
- **🎨 Time-based message grouping** — Messages within 5 min are grouped
- **🔐 Password Change** — Change your password from the profile page
- **3 Demo Users** — alice, admin, and bob seeded with conversations

---

## 🗄 Database Schema

```
users           — id, email, name, avatar, color, provider, password, status, bio, created
servers         — id, name, icon, description, owner, created
channels        — id, server_id, name, icon, topic, created
messages        — id, channel_id, user_id, content, edited, pinned, created
memberships     — user_id, server_id, role, joined
reactions       — id, message_id, user_id, emoji  (UNIQUE per user+emoji+message)
direct_messages — id, from_user, to_user, content, read, created
notifications   — id, user_id, content, read, created
```

The SQLite file `chat.db` is created automatically on first run.

---

## ⚙️ Google OAuth (Optional)

1. Go to https://console.cloud.google.com/
2. Create a project → APIs & Services → Credentials → OAuth 2.0 Client ID
3. Set Authorized redirect URI to: `http://localhost:8501`
4. Copy credentials to `config.json`

---

## 🌐 Deploy to Streamlit Cloud

1. Push this folder to a GitHub repo
2. Go to https://share.streamlit.io and connect your repo
3. Add secrets in the Streamlit Cloud dashboard:
   ```
   GOOGLE_CLIENT_ID = "..."
   GOOGLE_CLIENT_SECRET = "..."
   ```

---

## 📁 File Structure

```
streamline_pro/
├── app.py           ← Main Streamlit application (v2.0)
├── requirements.txt ← Python dependencies
├── config.json      ← Google OAuth credentials (don't commit this!)
├── chat.db          ← SQLite database (auto-created on first run)
└── README.md
```
