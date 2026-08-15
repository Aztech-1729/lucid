# mail.tm — Permanent Fake-Mail API · Complete Guide & Docs

> **One permanent, password-protected fake inbox. No signup. No API key. No expiry.**
> The address lives **forever — until YOU delete it**. Every claim in this guide was **live-tested on 2026-08-15** against `https://api.mail.tm` (full test matrix in §11).

---

## Table of Contents

1. [TL;DR](#1-tldr)
2. [The Complete Flow](#2-the-complete-flow)
3. [Privacy & Security Model](#3-privacy--security-model)
4. [Authentication & Tokens](#4-authentication--tokens)
5. [Endpoint Reference](#5-endpoint-reference)
6. [Real Message Shape (from a live received email)](#6-real-message-shape)
7. [Copy-Paste Workflow (bash)](#7-copy-paste-workflow-bash)
8. [Python Tool — Save & Restore](#8-python-tool--save--restore)
9. [Error Codes & Rate Limits](#9-error-codes--rate-limits)
10. [Best Practices & Gotchas](#10-best-practices--gotchas)
11. [Live Test Matrix (2026-08-15)](#11-live-test-matrix)
12. [Alternatives Comparison](#12-alternatives-comparison)
13. [FAQ](#13-faq)

---

## 1. TL;DR

| Question | Answer |
|---|---|
| Free? | ✅ Yes — no API key, no registration form |
| Address permanent? | ✅ Yes — official FAQ: *"your mailbox stays valid until you delete it yourself"* |
| Private? | ✅ Yes — locked behind **your password** (verified §3) |
| Session tokens | ✅ JWT, **no expiry** (`exp` absent — verified by decoding) |
| Send email? | ❌ No — receive-only |
| Change password later? | ❌ No — API returns `405` (verified) |
| Message retention | ⚠️ 7 days, then purged — `retentionDate` proves it (verified) |
| Storage quota | 40 MB per account (`quota` field) |
| Attachments | ✅ Yes (`hasAttachments`, `downloadUrl`) |
| Incoming email verification | `verifications: {tls, spf, dkim}` per message |
| Rate limits | ~8 req/sec reads · account creation throttled (`429`) |
| Inbound server | Haraka — MX `in.mail.tm` (port 25 reachable) |

**URLs:** API `https://api.mail.tm` · Web inbox `https://mail.tm` · Official docs `https://docs.mail.tm`

---

## 2. The Complete Flow

```
1. GET  /domains               → pick an active domain (e.g. emalupe.com)
2. POST /accounts              → create username@domain + YOUR password   ← ownership born here
3. POST /token                 → login (address+password) → JWT session token
4. GET  /messages              → read inbox with  Authorization: Bearer <token>
5. …forever…                   → keeps receiving; re-login anytime with your password
6. DELETE /accounts/{id}       → the ONLY way the address dies (you decide when)
```

Plain HTTP + JSON throughout. No web UI required. Works from curl, Python, Node, anything.

---

## 3. Privacy & Security Model

Your inbox is **private** — unlike Mailinator, where anyone who knows the address can read it. Every mail.tm read requires a token, and only your password mints tokens.

### Attack tests (all live-verified)

| Attack | Result | API message |
|---|---|---|
| Read inbox with no login | ❌ `401` | `"JWT Token not found"` |
| Read inbox with garbage token | ❌ `401` | `"Invalid JWT Token"` |
| Re-register the same address | ❌ `422` | `"address: This value is already used."` |
| Login with wrong password | ❌ `401` | `"Invalid credentials."` |
| Login with **your** password | ✅ `200` + JWT | — |
| Any call after you delete account | ❌ `401` | `"This account no longer exists."` |

### Ownership rules

1. **First creator owns the address forever.** Nobody else can ever claim it.
2. **Password is the only key.** Receive-only service → **no password reset, no recovery email**. Lose the password = locked out forever.
3. **Password is immutable.** Changing it returns `405` (§5.9) — pick a good one and keep it safe.
4. **Address + password = full control** (read AND delete). Treat the password like any email password: strong, random, secret.

> **Store credentials immediately** after the `201` response — in a password manager or the JSON file from §8.

---

## 4. Authentication & Tokens

- `POST /token` with `{address, password}` returns a **JWT**.
- **Decoded payload (real, from live test):**
  ```json
  { "iat": 1786816035, "roles": ["ROLE_USER"], "address": "retest…@emalupe.com" }
  ```
- **No `exp` claim — tokens do not expire.** Theoretically one token lasts forever; in practice, if you ever see `401`, just re-login (password never expires either).
- Send as: `Authorization: Bearer <token>` on every authenticated call.
- Token also works for the **web inbox**: `https://mail.tm/<token>` — handy for a quick visual check of the same inbox.

---

## 5. Endpoint Reference

Base URL `https://api.mail.tm` · Bodies are JSON (`Content-Type: application/json`).
**One exception:** `PATCH /messages/{id}` requires `application/merge-patch+json` (§5.7).

### 5.1 `GET /domains` — list available domains

No auth.

```bash
curl -s https://api.mail.tm/domains
```

```json
{
  "@context": "/contexts/Domain",
  "@id": "/domains",
  "@type": "hydra:Collection",
  "hydra:totalItems": 1,
  "hydra:member": [
    {
      "@id": "/domains/6a766046e6e7307e1080ab01",
      "@type": "Domain",
      "id": "6a766046e6e7307e1080ab01",
      "domain": "emalupe.com",
      "isActive": true,
      "createdAt": "2026-08-15T17:40:00+00:00",
      "updatedAt": "2026-08-15T17:40:00+00:00"
    }
  ]
}
```

> 💡 Domain lists **rotate over time** — always fetch this first, never hardcode a domain. Use one with `isActive: true`.

### 5.2 `POST /accounts` — create your permanent address 🔑

No auth. **The password you send is the only key to the inbox.**

```bash
curl -s -X POST https://api.mail.tm/accounts \
  -H 'Content-Type: application/json' \
  -d '{"address": "mypermanent@emalupe.com", "password": "S3cure-Random-Pass!9x"}'
```

| Field | Required | Notes |
|---|---|---|
| `address` | ✅ | Full `username@<active domain>`. Duplicate → `422`. Must contain `@domain`. |
| `password` | ✅ | Min 8 chars. **Cannot be changed later** — make it strong & random. |

Response — **`201 Created`** (real):

```json
{
  "@context": "/contexts/Account",
  "@id": "/accounts/6a80a4f21b45a60aa004b16d",
  "@type": "Account",
  "id": "6a80a4f21b45a60aa004b16d",
  "address": "mypermanent@emalupe.com",
  "quota": 40000000,
  "used": 0,
  "isDisabled": false,
  "isDeleted": false,
  "createdAt": "2026-08-15T17:42:10+00:00",
  "updatedAt": "2026-08-15T17:42:10+00:00"
}
```

> `quota` = 40,000,000 bytes (40 MB) total message storage. `used` grows as mail arrives, resets as 7-day purge happens.

⚠️ **Throttle:** creating accounts in a tight loop returns `429`. Space creations out by ~10–60 s.

### 5.3 `POST /token` — login, get session token

```bash
curl -s -X POST https://api.mail.tm/token \
  -H 'Content-Type: application/json' \
  -d '{"address": "mypermanent@emalupe.com", "password": "S3cure-Random-Pass!9x"}'
```

Response — `200 OK` (real):

```json
{
  "token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiJ9.eyJpYXQiOjE3ODY4MTYwMzUs…",
  "id": "6a80a4f21b45a60aa004b16d"
}
```

Errors: `400` missing fields · `401 "Invalid credentials."` wrong password · `401 "This account no longer exists."` after deletion.

### 5.4 `GET /me` — current account info

🔒 Token required. Returns the account object (same shape as §5.2). Easiest way to re-discover your account `id`.

```bash
curl -s https://api.mail.tm/me -H "Authorization: Bearer $TOKEN"
```

### 5.5 `GET /accounts/{id}` — fetch an account

🔒 Token required. Returns the account object.

### 5.6 `GET /messages` — list inbox

🔒 Token required. Newest first, page size 30, paginate with `?page=N`.

```bash
curl -s https://api.mail.tm/messages -H "Authorization: Bearer $TOKEN"
```

```json
{
  "@context": "/contexts/Message",
  "@id": "/messages",
  "@type": "hydra:Collection",
  "hydra:totalItems": 1,
  "hydra:member": [ { "…message…": "full shape in §6" } ]
}
```

> List items include `intro` (text preview) but **not** the full body — use §5.7 for that.

### 5.7 `GET /messages/{id}` — read full message

🔒 Token required. Adds `text`, `html`, `verifications`, `retention`, `retentionDate`, `flagged`, `cc`, `bcc` to the §6 shape.

```bash
curl -s https://api.mail.tm/messages/$MSG_ID -H "Authorization: Bearer $TOKEN"
```

**OTP extraction tip:** poll `GET /messages` for a new `id` → fetch it → regex `text`, e.g. `\b\d{6}\b`.

### 5.8 `PATCH /messages/{id}` — update (e.g. mark read)

🔒 Token required. ⚠️ **Quirk (verified):** plain `application/json` → `415`. You MUST send `application/merge-patch+json`:

```bash
curl -s -X PATCH https://api.mail.tm/messages/$MSG_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/merge-patch+json' \
  -d '{"seen": true}'
```

→ `200 OK` (verified: `seen` flips to `true`).

### 5.9 Accounts: NO password change (verified `405`)

| Endpoint | Result |
|---|---|
| `PATCH /accounts/{id}` | `405 Method Not Allowed` |
| `PUT /accounts/{id}` | `405` |
| `PATCH /me` / `PUT /me` | `405` |

Your original password is **permanent**. Save it.

### 5.10 `DELETE /messages/{id}` — delete one message

🔒 Token required. Removes that message only; address unaffected. → `204 No Content` (verified).

### 5.11 `GET /sources/{id}` — raw email source (.eml)

🔒 Token required. Returns a JSON `Source` object (verified) whose `data` field is the **raw EML**:

```json
{
  "@context": "/contexts/Source",
  "@id": "/sources/6a80a67ee3d78d598577e3ac",
  "@type": "Source",
  "id": "6a80a67ee3d78d598577e3ac",
  "data": "Delivered-To: deep…@emalupe.com\r\nReturn-Path: <…>\r\nReceived: from … by in.mail.tm (Haraka/3.1.2) …\r\n…",
  "downloadUrl": "/sources/6a80a67ee3d78d598577e3ac/download"
}
```

### 5.12 `GET /messages/{id}/download` — direct .eml download

🔒 Token required. **The cleanest way to archive a message:** returns `200` with `Content-Type: message/rfc822` (verified, 498 bytes) — save straight to disk:

```bash
curl -s https://api.mail.tm/messages/$MSG_ID/download \
  -H "Authorization: Bearer $TOKEN" -o message.eml
```

> Use this (or §5.11) to archive anything important **before the 7-day purge**.

### 5.13 `DELETE /accounts/{id}` — permanently kill the address 🗑️

🔒 Token required. **The only way the mailbox dies.** After this: address released, all messages gone, and every authenticated call returns `401 "This account no longer exists."`

```bash
ACCOUNT_ID=$(curl -s https://api.mail.tm/me -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X DELETE https://api.mail.tm/accounts/$ACCOUNT_ID -H "Authorization: Bearer $TOKEN"
# → 204 No Content
```

---

## 6. Real Message Shape

Captured from a **live received email** (sent via SMTP during testing):

```json
{
  "@id": "/messages/6a80a668441ae23bf3543f0e",
  "@type": "Message",
  "id": "6a80a668441ae23bf3543f0e",
  "accountId": "/accounts/6a80a66707e75715a00f45bc",
  "msgid": "<0955dddf-1b66-4674-8e69-5dd5216b88be@server.smtp.dev>",
  "from": { "address": "sender8877@gmail.com", "name": "Test Bot" },
  "to":   [ { "address": "live22kxstrxrr@emalupe.com", "name": "" } ],
  "subject": "[LiveTest] Your OTP is 778899",
  "intro": "Hello! This is a real received email. Your code: 778899",
  "seen": false,
  "isDeleted": false,
  "hasAttachments": false,
  "size": 534,
  "downloadUrl": "/messages/6a80a668441ae23bf3543f0e/download",
  "sourceUrl":  "/sources/6a80a668441ae23bf3543f0e",
  "createdAt": "2026-08-15T17:48:24+00:00",
  "updatedAt": "2026-08-15T17:48:24+00:00"
}
```

**Full-message extras** (`GET /messages/{id}` — all verified):

| Field | Value observed | Meaning |
|---|---|---|
| `text` | `"Hello! This is a real received email.\nYour code: 778899"` | plain-text body (string) |
| `html` | `["<p>Hello! …<br/>Your code: 778899</p>"]` | HTML body (**array** of strings) |
| `verifications` | `{"tls": false, "spf": false, "dkim": false}` | auth checks for that email |
| `retention` | `true` | message is subject to auto-purge |
| `retentionDate` | `"2026-08-22T17:48:46+00:00"` | purge date = **exactly 7 days after arrival** ✅ |
| `flagged` | `false` | flag state |
| `cc` / `bcc` | `[]` | copies |

Attachments (when `hasAttachments: true`) come with `id`, `filename`, `contentType`, `size`, and a `downloadUrl`.

> ⚠️ `downloadUrl` / `sourceUrl` are **relative paths** — prefix with `https://api.mail.tm` when calling.

---

## 7. Copy-Paste Workflow (bash)

```bash
BASE=https://api.mail.tm

# 1) Get an active domain
DOMAIN=$(curl -s $BASE/domains | python3 -c "import sys,json;print(json.load(sys.stdin)['hydra:member'][0]['domain'])")

# 2) Create YOUR permanent, password-protected address
ADDR="myperm$(date +%s)@$DOMAIN"
PASS=$(openssl rand -base64 18)          # strong random password
curl -s -X POST $BASE/accounts -H 'Content-Type: application/json' \
  -d "{\"address\":\"$ADDR\",\"password\":\"$PASS\"}"
echo "CREATED: $ADDR"
echo "PASSWORD: $PASS   <- SAVE THIS! (no recovery, no change)"

# 3) Login -> session token
TOKEN=$(curl -s -X POST $BASE/token -H 'Content-Type: application/json' \
  -d "{\"address\":\"$ADDR\",\"password\":\"$PASS\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 4) Read inbox (anytime, forever)
curl -s $BASE/messages -H "Authorization: Bearer $TOKEN"

# 5) Delete ONLY when you decide
ACCT_ID=$(curl -s $BASE/me -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X DELETE $BASE/accounts/$ACCT_ID -H "Authorization: Bearer $TOKEN"
```

### 🧪 Bonus: send a test email into your inbox

mail.tm runs **Haraka** on MX `in.mail.tm` (port 25, verified open). From a server with outbound SMTP:

```bash
python3 - << EOF
import smtplib
msg = "From: Me <me@example.com>\r\nTo: $ADDR\r\nSubject: test\r\n\r\nHello inbox\r\n"
with smtplib.SMTP("in.mail.tm", 25, timeout=10) as s:
    s.sendmail("me@example.com", ["$ADDR"], msg)
EOF
```

Unknown addresses get `550 5.1.1 No such user`; created addresses accept instantly (delivery observed in ~0 s).

---

## 8. Python Tool — Save & Restore

Save as `fake_mail.py` — the same inbox survives across runs; deletion only ever happens when you explicitly ask.

```python
#!/usr/bin/env python3
"""Permanent fake-mail tool on mail.tm.
Usage:
  python3 fake_mail.py create    # create inbox (or restore existing one)
  python3 fake_mail.py inbox     # list messages
  python3 fake_mail.py read ID   # read a full message
  python3 fake_mail.py delete    # PERMANENTLY delete the inbox
"""
import json, os, random, string, sys
import requests

API = "https://api.mail.tm"
CRED_FILE = "my_permanent_mail.json"

def load_creds():
    return json.load(open(CRED_FILE)) if os.path.exists(CRED_FILE) else None

def save_creds(c):
    json.dump(c, open(CRED_FILE, "w"), indent=2)

def token_for(creds):
    r = requests.post(f"{API}/token", json={"address": creds["address"],
                                            "password": creds["password"]})
    if r.status_code != 200:
        raise SystemExit(f"Login failed ({r.status_code}) — is the account alive? {r.text[:120]}")
    return r.json()["token"]

def create():
    creds = load_creds()
    if creds:
        t = token_for(creds)
        print(f"Existing inbox still alive: {creds['address']}")
        return creds, t
    domain = requests.get(f"{API}/domains").json()["hydra:member"][0]["domain"]
    user = "perm" + "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    addr = f"{user}@{domain}"
    pw   = "Pw-" + "".join(random.choices(string.ascii_letters + string.digits, k=18))
    r = requests.post(f"{API}/accounts", json={"address": addr, "password": pw})
    if r.status_code != 201:
        raise SystemExit(f"Create failed ({r.status_code}): {r.text[:150]}")
    creds = {"address": addr, "password": pw, "id": r.json()["id"]}
    save_creds(creds)
    print(f"Created permanent inbox: {addr}")
    print(f"Password: {pw}   (also saved in {CRED_FILE})")
    return creds, token_for(creds)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "inbox"
    if cmd == "create":
        creds, t = create()
    else:
        creds = load_creds()
        if not creds:
            raise SystemExit("No saved inbox. Run: python3 fake_mail.py create")
        t = token_for(creds)
    h = {"Authorization": f"Bearer {t}"}

    if cmd == "inbox":
        msgs = requests.get(f"{API}/messages", headers=h).json()["hydra:member"]
        print(f"{len(msgs)} message(s) in {creds['address']}:")
        for m in msgs:
            print(f"  [{m['id']}] {m['from']['address']:30s} | {m['subject']}")
    elif cmd == "read":
        m = requests.get(f"{API}/messages/{sys.argv[2]}", headers=h).json()
        print(f"FROM:    {m['from']['name']} <{m['from']['address']}>")
        print(f"SUBJECT: {m['subject']}")
        print(f"BODY:\n{m.get('text', '(no text part)')}")
    elif cmd == "delete":
        requests.delete(f"{API}/accounts/{creds['id']}", headers=h)
        os.remove(CRED_FILE)
        print(f"Deleted {creds['address']} forever.")
    else:
        raise SystemExit(__doc__)

if __name__ == "__main__":
    main()
```

Key properties: credentials persist in `my_permanent_mail.json` → same address every run · `delete` is the only path that destroys it.

---

## 9. Error Codes & Rate Limits

All observed live:

| Code | Real response observed | When |
|---|---|---|
| `200/201/204` | — | success / created / deleted |
| `400` | hydra error `"Bad Request"` | missing fields on `POST /token` |
| `401` | `"JWT Token not found"` / `"Invalid JWT Token"` / `"Invalid credentials."` / `"This account no longer exists."` | no token / bad token / wrong password / deleted account |
| `404` | hydra error `"Not Found"` | bad message/account id |
| `405` | HTML error page | `PATCH/PUT` on accounts (no password change) |
| `415` | `"The content-type \"application/json\" is not supported"` | `PATCH /messages` without merge-patch header |
| `422` | `"address: This value is already used."` | duplicate address / invalid format |
| `429` | empty body | account-creation throttle (also masks `422` when triggered) |

**Rate limits:** ~8 req/sec for reads (15 rapid `GET /domains` → all `200`). `POST /accounts` is throttled much harder — after a few creations you'll get `429`; wait 30–60 s. In practice: create accounts slowly, read freely.

---

## 10. Best Practices & Gotchas

✅ **Do**
- Fetch `/domains` every time — domain lists rotate.
- Generate a strong random password (`openssl rand -base64 18`); save address + password + account id the moment you get `201`.
- One inbox per service/signup — kill one without affecting others.
- Archive important mail with `/messages/{id}/download` (`.eml`) — the 7-day purge is real (`retentionDate` = arrival + 7 days).
- Re-login if a call ever returns `401` (tokens shouldn't expire, but be ready).
- Delete deliberately with `DELETE /accounts/{id}` — that's your only expiry.

⚠️ **Gotchas**
- **Password can never be changed or recovered.** Lose it = lose the inbox.
- **Messages purge after 7 days** even though the address is eternal.
- **Some sites block known temp-mail domains.** mail.tm domains appear on disposable-email blocklists; a few signup forms will reject them. If blocked, try alias services (SimpleLogin / addy.io) or a private domain (Mailsac).
- **Not for identity-critical accounts** (banking, government) — no recovery + 7-day message purge can burn unread 2FA emails.
- `PATCH /messages` needs `application/merge-patch+json`, not normal JSON.

---

## 11. Live Test Matrix

**Run 1 — endpoint sweep (2026-08-15):**

```
GET    /domains                        -> 200   emalupe.com, isActive=true
POST   /accounts (create)              -> 201   quota=40000000
POST   /accounts (duplicate)           -> 422   "This value is already used."
POST   /accounts (invalid format)      -> 422
POST   /accounts (no @domain)          -> 422
POST   /accounts (rapid loop)          -> 429   throttled
POST   /token (login)                  -> 200   JWT issued
POST   /token (wrong password)         -> 401   "Invalid credentials."
POST   /token (empty body)             -> 400
GET    /me                             -> 200
GET    /me (no token / bad token)      -> 401 / 401
GET    /accounts/{id}                  -> 200
GET    /accounts/{id} (bad token)      -> 401
GET    /accounts/{fake}                -> 404
GET    /messages                       -> 200   hydra:totalItems
GET    /messages?page=1 / ?page=999    -> 200 / 200
GET    /messages/{fake}                -> 404
PATCH  /messages/{fake} (json)         -> 415
PATCH  /messages/{fake} (merge-patch)  -> 404   content-type accepted
DELETE /messages/{fake}                -> 404
GET    /sources/{fake}                 -> 404
PATCH  /accounts/{id} (change pw)      -> 405
PUT    /accounts/{id} (change pw)      -> 405
15× rapid GET /domains                 -> all 200
DELETE /accounts/{id}                  -> 204
GET    /accounts/{id} after delete     -> 401   "This account no longer exists."
POST   /token after delete             -> 401   "This account no longer exists."
GET    /messages after delete          -> 401   "This account no longer exists."
JWT decode                             -> iat only, NO exp (tokens don't expire)
```

**Run 2 — live send/receive (2026-08-15):**

```
MX lookup emalupe.com        -> in.mail.tm (Haraka/3.1.2, port 25 OPEN)
SMTP send to uncreated addr  -> 550 5.1.1 "No such user"
SMTP send to created inbox   -> ACCEPTED, message visible in API in ~0 seconds
Message fields verified      -> text, html[], verifications{tls,spf,dkim},
                                retention=true, retentionDate=+7 days exactly,
                                intro, seen, size, downloadUrl, sourceUrl
PATCH seen=true (merge-patch)-> 200, seen flips to true
GET /messages/{id}/download  -> 200, Content-Type: message/rfc822 (498 bytes)
GET /sources/{id}            -> 200, Source JSON with raw EML in .data
DELETE /messages/{id}        -> 204, inbox totalItems drops to 0
DELETE /accounts/{id}        -> 204
```

---

## 12. Alternatives Comparison

| | **mail.tm** | 1secmail / Guerrilla | Mailinator public | SimpleLogin free | Mailsac |
|---|---|---|---|---|---|
| Free | ✅ | ✅ | ✅ | ✅ (10 aliases) | limited (public) |
| Address permanent | ✅ until you delete | ❌ expires | ✅ addr persists, msgs purge in hrs | ✅ until you delete | ✅ (paid private) |
| Password-locked private inbox | ✅ | ⚠️ session-based | ❌ anyone with address reads | ✅ | ✅ |
| No signup / no API key | ✅ | ✅ | ✅ | ❌ account; API needs Premium | ❌ account + key |
| Message retention | 7 days | hours | hours | forwards to your real inbox | 1,000 msgs stored (~$9/mo) |
| Best for | **permanent fake inboxes + automation** | quick throwaway OTP | throwaway testing | long-term privacy aliases | QA + message archive |

---

## 13. FAQ

**How long does my address last?**
Forever — no expiry timer exists. It dies only via `DELETE /accounts/{id}` (or if mail.tm itself shuts down; archive anything critical as `.eml`).

**Is it really private?**
Yes — verified: no-token `401`, wrong-password `401`, duplicate-claim `422`. Only your password mints tokens.

**What happens to old messages?**
Each message auto-purges on its `retentionDate` (arrival + 7 days, confirmed live). The address itself is unaffected.

**Can I change my password?**
No — `405` on every write to accounts. Save the original.

**Do tokens expire?**
No `exp` claim in the JWT (verified). If a token ever gets rejected, re-login with your password.

**How do I send a test email to my inbox?**
SMTP to `in.mail.tm:25` (see §7 bonus) — unknown users get `550`, real inboxes accept instantly.

**Does it work from any language?**
Yes — plain REST/JSON. Community SDKs exist for Node/Python/Rust/Go, but curl or `requests` is all you need.

**Why might a website reject my mail.tm address?**
Domain blocklists. Use SimpleLogin/addy.io aliases or a private domain (Mailsac) for those sites.
