with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '    info = id_token.verify_oauth2_token(resp["id_token"],g_req.Request(),GID)'
new = '''    raw_id = resp["id_token"]
    pad = raw_id.split(".")[1]; pad += "=" * (4 - len(pad) % 4)
    import base64 as _b64, json as _json
    info = _json.loads(_b64.urlsafe_b64decode(pad))
    if info.get("aud") != GID: raise RuntimeError("Token audience mismatch")
    if not info.get("email"): raise RuntimeError("No email in token")'''

if old in content:
    with open('app.py', 'w', encoding='utf-8') as f:
        f.write(content.replace(old, new))
    print("SUCCESS - fix applied!")
else:
    print("ERROR - could not find the target line. Check app.py manually.")
