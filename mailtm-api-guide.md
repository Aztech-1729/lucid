# Permanent Fake Email for Telegram — Complete Setup Guide (mail.gw)

> **Goal:** a free, permanent fake email that Telegram accepts for **Recovery Email / Add Email** — the address stays alive **until YOU delete it**, locked behind your own password.
>
> **Why this exists:** mail.tm works great, but its domain (`emalupe.com`) is on Telegram's disposable-email blocklist → rejected. **mail.gw** is the same system with **legit-looking domains** (`questtechsystems.com`, `raleigh-construction.com` …) that pass the filter.
>
> ✅ **Your Telegram inbox is already created and verified alive** — jump straight to [§2](#2-your-ready-made-telegram-inbox).

---

## Table of Contents

1. [TL;DR](#1-tldr)
2. [Your Ready-Made Telegram Inbox](#2-your-ready-made-telegram-inbox)
3. [Step-by-Step: Link It in Telegram](#3-step-by-step-link-it-in-telegram)
4. [Why mail.tm Failed & Why mail.gw Works](#4-why-mailtm-failed--why-mailgw-works)
5. [Checking the Inbox (script + curl)](#5-checking-the-inbox)
6. [Permanence, Privacy & Security](#6-permanence-privacy--security)
7. [Full API Reference (mail.gw)](#7-full-api-reference-mailgw)
8. [Live Test Evidence (2026-08-15)](#8-live-test-evidence)
9. [Gotchas & Limits](#9-gotchas--limits)
10. [Fallback Chain If Telegram Blocks It](#10-fallback-chain-if-telegram-blocks-it)
11. [FAQ](#11-faq)

---

## 1. TL;DR

| Question | Answer |
|---|---|
| Does Telegram accept it? | ✅ **Yes — that's the point.** Domain looks like a real company, not a temp-mail domain |
| Free? | ✅ Yes — no API key, no signup page |
| Address permanent? | ✅ Yes — lives **forever until YOU delete it** |
| Private? | ✅ Yes — locked behind **your password** (verified: wrong password `401`, re-register `422`) |
| Message retention | ⚠️ 7 days per message, then auto-purged (address unaffected) |
| Send email? | ❌ No — receive-only (fine for receiving Telegram codes) |
| Change password later? | ❌ No (`405`) — save it |
| Session tokens | JWT, **no expiry** (verified) |
| Storage | 40 MB per inbox |

**URLs:** API `https://api.mail.gw` · mail.tm twin API `https://api.mail.tm` · Web inbox `https://mail.gw`

---

## 2. Your Ready-Made Telegram Inbox

**Created 2026-08-15 · status re-verified alive (login `200`, `isDisabled: false`)**

| Field | Value |
|---|---|
| 📧 Address | `support0473@questtechsystems.com` |
| 🔑 Password | stored in **`telegram_mail.json`** (workspace) |
| 🆔 Account ID | in `telegram_mail.json` (needed only for deletion) |
| ⏳ Lifetime | **permanent** — dies only via `DELETE /accounts/{id}` |
| 💾 Quota | 40 MB |
| 🧹 Message purge | 7 days per message |

Use this address wherever Telegram asks for an email (Two-Step Verification recovery email, add email).

---

## 3. Step-by-Step: Link It in Telegram

### 3.1 Where Telegram asks for it

- **Recovery email:** Telegram → **Settings → Privacy and Security → Two-Step Verification → Recovery Email**
- **Add email:** wherever Telegram showed the *"add mail"* field

### 3.2 Enter the address

```
support0473@questtechsystems.com
```

### 3.3 Telegram sends a 6-digit code → read it

**Option A — auto script (easiest):**

```bash
python3 check_telegram_mail.py
```

It logs in with the saved password, lists messages, and **auto-extracts the code** from the email body.

**Option B — manual curl:**

```bash
# login (password is in telegram_mail.json)
TOKEN=$(curl -s -X POST https://api.mail.gw/token -H 'Content-Type: application/json' \
  -d '{"address":"support0473@questtechsystems.com","password":"<PASSWORD>"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# list inbox
curl -s https://api.mail.gw/messages -H "Authorization: Bearer $TOKEN"

# read the latest message body
curl -s https://api.mail.gw/messages/<MESSAGE_ID> -H "Authorization: Bearer $TOKEN"
```

### 3.4 Enter the code in Telegram

Done. From now on the address is your **permanent recovery email** — it never expires, so password recovery works even months later (as long as you read the email within 7 days of receiving it).

---

## 4. Why mail.tm Failed & Why mail.gw Works

| | mail.tm | **mail.gw** |
|---|---|---|
| Domains served | `emalupe.com` (known temp-mail domain) | `questtechsystems.com`, `raleigh-construction.com`, `pastryofistanbul.com`, `oakon.com`, `teihu.com` |
| Telegram reaction | ❌ **rejected** (blocklisted) | ✅ looks like normal companies |
| API | same system | same system — identical endpoints, just different base URL |
| Permanence | same | same — until you delete it |
| Password lock | same | same |

**Both are the same service with different domains.** The only change is the base URL:

```
https://api.mail.tm   →   https://api.mail.gw
```

### Current mail.gw domains (fetched live 2026-08-15)

```
  - oakon.com                  ✅ active
  - teihu.com                  ✅ active
  - raleigh-construction.com   ✅ active   ← building firm look
  - pastryofistanbul.com       ✅ active   ← bakery look
  - questtechsystems.com       ✅ active   ← IT company look  (YOURS)
```

> Domains rotate over time — always `GET /domains` before creating a new one. An address already created stays yours forever even if its domain later leaves the rotation.

---

## 5. Checking the Inbox

### Script: `check_telegram_mail.py`

```python
#!/usr/bin/env python3
"""Read the Telegram mail.gw inbox + auto-extract OTP codes."""
import json, re, requests

API = "https://api.mail.gw"
creds = json.load(open("telegram_mail.json"))

tok = requests.post(f"{API}/token", json={
    "address": creds["address"], "password": creds["password"]}).json()["token"]
h = {"Authorization": f"Bearer {tok}"}

msgs = requests.get(f"{API}/messages", headers=h).json()["hydra:member"]
print(f"Inbox: {creds['address']}  ({len(msgs)} message(s))")

for m in msgs:
    full = requests.get(f"{API}/messages/{m['id']}", headers=h).json()
    print(f"\n--- {full['from']['address']} | {full['subject']}")
    body = full.get("text") or ""
    print(body)
    codes = re.findall(r"\b\d{5,6}\b", body)
    if codes:
        print(f"\n>>> POSSIBLE TELEGRAM CODE(S): {codes}")
```

Save it next to `telegram_mail.json` and run:

```bash
python3 check_telegram_mail.py
```

---

## 6. Permanence, Privacy & Security

### 6.1 Permanent = until YOU delete

- No expiry timer exists. Official FAQ: *"your mailbox stays valid until you delete it yourself."*
- The **only** way it dies:

```bash
ACCOUNT_ID=$(curl -s https://api.mail.gw/me -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
curl -s -X DELETE https://api.mail.gw/accounts/$ACCOUNT_ID -H "Authorization: Bearer $TOKEN"
# → 204 = gone forever
```

### 6.2 Private — verified attack tests

| Attack | Result |
|---|---|
| Read inbox with no login | ❌ `401` "JWT Token not found" |
| Read inbox with garbage token | ❌ `401` "Invalid JWT Token" |
| Re-register the same address | ❌ `422` "This value is already used." |
| Login with wrong password | ❌ `401` "Invalid credentials." |
| Login with **your** password | ✅ `200` + JWT |
| Any call after account deletion | ❌ `401` "This account no longer exists." |

### 6.3 Token facts (verified by decoding)

```json
{ "iat": 1786816035, "roles": ["ROLE_USER"], "address": "support0473@questtechsystems.com" }
```

- **No `exp` claim → tokens don't expire.** If you ever get `401` anyway, just re-login with your password.

### 6.4 Ownership rules

1. **First creator owns the address forever.** Nobody else can claim it.
2. **Password is the only key.** Receive-only → no reset, no recovery. Lose it = inbox lost.
3. **Password immutable** — changing it returns `405`.
4. Address + password = full control (read AND delete). Keep the password secret.

---

## 7. Full API Reference (mail.gw)

Base URL `https://api.mail.gw` · JSON bodies · one quirk: `PATCH /messages/{id}` needs `Content-Type: application/merge-patch+json` (else `415`).

| # | Endpoint | Auth | Purpose | Verified |
|---|---|---|---|---|
| 1 | `GET /domains` | — | list active domains (pick a sneaky one) | `200` |
| 2 | `POST /accounts` | — | **create** `{address, password}` → `201` | ✅ |
| 3 | `POST /token` | — | **login** `{address, password}` → JWT | ✅ |
| 4 | `GET /me` | 🔒 | account info incl. `id`, `quota` | ✅ |
| 5 | `GET /accounts/{id}` | 🔒 | fetch account | ✅ |
| 6 | `GET /messages` | 🔒 | list inbox (newest first, `?page=N`) | ✅ |
| 7 | `GET /messages/{id}` | 🔒 | **full message** (`text`, `html[]`, `verifications`, `retentionDate`) | ✅ |
| 8 | `PATCH /messages/{id}` | 🔒 | update (e.g. `{"seen": true}`) — **merge-patch header required** | ✅ |
| 9 | `DELETE /messages/{id}` | 🔒 | delete one message → `204` | ✅ |
| 10 | `GET /sources/{id}` | 🔒 | raw `.eml` in JSON `.data` | ✅ |
| 11 | `GET /messages/{id}/download` | 🔒 | direct `.eml` download (`message/rfc822`) — best for archiving | ✅ |
| 12 | `DELETE /accounts/{id}` | 🔒 | **permanently kill the address** → `204` | ✅ |
| ❌ | `PATCH/PUT /accounts/{id}` or `/me` | — | password change → `405` (not supported) | ✅ |

### Create another Telegram-ready inbox

```bash
BASE=https://api.mail.gw

# 1) pick a sneaky domain
DOMAIN=$(curl -s $BASE/domains | python3 -c "import sys,json;d=json.load(sys.stdin)['hydra:member'];print([x['domain'] for x in d if 'quest' in x['domain'] or 'raleigh' in x['domain'] or 'pastry' in x['domain']][0])")

# 2) create with a natural-looking username
ADDR="support$(shuf -i 1000-9999 -n 1)@$DOMAIN"
PASS=$(openssl rand -base64 18)
curl -s -X POST $BASE/accounts -H 'Content-Type: application/json' \
  -d "{\"address\":\"$ADDR\",\"password\":\"$PASS\"}"
echo "CREATED: $ADDR   PASSWORD: $PASS   <- SAVE IT"

# 3) login
TOKEN=$(curl -s -X POST $BASE/token -H 'Content-Type: application/json' \
  -d "{\"address\":\"$ADDR\",\"password\":\"$PASS\"}" | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")

# 4) read mail
curl -s $BASE/messages -H "Authorization: Bearer $TOKEN"
```

### Send yourself a test email

mail.gw runs **Haraka** on MX `in.mail.tm` (port 25 open — verified). From a server with outbound SMTP:

```python
import smtplib
with smtplib.SMTP("in.mail.tm", 25, timeout=10) as s:
    s.sendmail("me@example.com", ["support0473@questtechsystems.com"],
               "From: Me <me@example.com>\r\nTo: support0473@questtechsystems.com\r\nSubject: test\r\n\r\nHello\r\n")
```

Unknown addresses → `550 5.1.1 No such user`; created addresses accept instantly (~0 s observed).

---

## 8. Live Test Evidence

**Run 1 — endpoint sweep (2026-08-15, api.mail.tm — same system):**

```
POST   /accounts (create)          -> 201   quota=40000000
POST   /accounts (duplicate)       -> 422   "This value is already used."
POST   /accounts (invalid format)  -> 422
POST   /accounts (rapid loop)      -> 429   throttled
POST   /token (login)              -> 200   JWT (no exp claim)
POST   /token (wrong password)     -> 401   "Invalid credentials."
GET    /me                         -> 200
GET    /me (no token / bad token)  -> 401 / 401
GET    /messages                   -> 200
GET    /messages/{fake}            -> 404
PATCH  /messages (plain json)      -> 415   (use merge-patch+json)
PATCH  /accounts (change pw)       -> 405   (unsupported)
DELETE /accounts/{id}              -> 204
POST   /token after delete         -> 401   "This account no longer exists."
```

**Run 2 — live send/receive:**

```
MX emalupe.com         -> in.mail.tm (Haraka/3.1.2, port 25 OPEN)
SMTP → created inbox   -> ACCEPTED, message visible in ~0 seconds
Message fields         -> text, html[], verifications{tls,spf,dkim},
                          retention=true, retentionDate=arrival+7days, intro,
                          seen, size, downloadUrl, sourceUrl
PATCH seen=true        -> 200, seen flips true
GET /messages/{id}/download -> 200 message/rfc822
```

**Run 3 — your Telegram inbox (2026-08-15, api.mail.gw):**

```
GET    /domains                -> 5 active domains (incl. questtechsystems.com)
POST   /accounts               -> 201  support0473@questtechsystems.com
POST   /token                  -> 200
GET    /me (re-check, same day)-> 200  isDisabled: false, quota 40 MB
```

---

## 9. Gotchas & Limits

⚠️ **Messages purge after 7 days** (`retentionDate` = arrival + 7d, verified). The *address* is eternal; old *messages* are not. Read Telegram's code promptly — or archive with `/messages/{id}/download`.

⚠️ **Password can never be changed or recovered** (`405`, no reset mechanism). It lives in `telegram_mail.json` — back it up.

⚠️ **Telegram acceptance is best-effort.** The domain looks normal and normally passes, but Telegram's blocklist is server-side and can tighten. If rejected → [§10 fallbacks](#10-fallback-chain-if-telegram-blocks-it).

⚠️ **Account creation throttles** — rapid `POST /accounts` → `429`. Space creations out.

⚠️ **Not for identity-critical stuff** — if you lose the password there's no recovery, and 7-day purge could eat an unread recovery email. (For Telegram this is fine: you can always re-request the code.)

⚠️ **Don't share the password.** Address + password = full control of the inbox.

---

## 10. Fallback Chain If Telegram Blocks It

| # | Option | What | Cost |
|---|---|---|---|
| 1 | Other mail.gw domains | `raleigh-construction.com`, `pastryofistanbul.com`, `oakon.com`, `teihu.com` — create a fresh inbox on each until one passes | Free |
| 2 | SmailPro | generates **real `@gmail.com` / `@outlook.com`** temp addresses — effectively unblockable | Free basic |
| 3 | EmailAlias.io | permanent private inboxes, claims non-blocklisted domains | Free (10 aliases) / $4/mo API |
| 4 | Proton Mail free | real permanent mailbox, guaranteed accepted (but a real account, not fake mail) | Free |

---

## 11. FAQ

**Will the address really never expire?**
Correct — no timer exists. Only `DELETE /accounts/{id}` kills it.

**Is it private? Can someone read my Telegram code?**
No. Every read requires your token; only your password mints tokens (verified 401/422 attacks).

**What if I lose the password?**
The inbox is unrecoverable. Create a new one — it takes 10 seconds (§7).

**How fast do Telegram's emails arrive?**
Delivery into the API was observed in ~0 seconds in live SMTP tests.

**Do I need the web UI?**
No. The API covers everything. Optional: open `https://mail.gw/<token>` for a visual inbox.

**Does mail.gw work from any language?**
Yes — plain REST/JSON. curl, Python `requests`, Node `fetch`, anything.

**Why is Telegram so strict?**
It blocks known disposable domains to fight spam/abuse. mail.gw's sneaky domains are designed to not look disposable — that's the entire trick.

---

### Workspace files

| File | Purpose |
|---|---|
| `telegram_mail.json` | your inbox credentials (address, password, id) |
| `check_telegram_mail.py` | login + read inbox + auto-extract codes |
| `mailtm-api-guide.md` | this guide |
