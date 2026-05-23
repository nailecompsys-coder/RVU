# Email Setup — Gmail / Google Workspace SMTP



RVU uses **`email_service.py`** for magic-link and notification email.  

One App Password on one Google Workspace account is all you need.



---



## Step 1 — Pick a sending account



Use any Google Workspace account at `@midfloridasurgical.com`.

Recommended: a dedicated address like `noreply@midfloridasurgical.com` so

recipients see a clean sender name. A real personal account works too.



---



## Step 2 — Enable 2-Step Verification (required for App Passwords)



1. Open **[myaccount.google.com](https://myaccount.google.com)** and sign in

   as the sending account.

2. Go to **Security** → **2-Step Verification**.

3. If it's not already on, turn it on (follow the prompts — takes ~2 minutes).



---



## Step 3 — Create an App Password



1. Still on **Security**, scroll down to **App passwords**

   (only visible once 2-Step Verification is enabled).

2. Click **App passwords**.

3. Under "App name" type: `RVU Mailer`

4. Click **Create**.

5. Google shows a **16-character password** (format: `xxxx xxxx xxxx xxxx`).

6. **Copy it now** — Google will never show it again.



> If you don't see "App passwords" in the Security menu, your Google Workspace

> admin may have disabled it. Log into **admin.google.com** → Security →

> Authentication → App passwords → Enable for all users (or your OU).



---



## Step 4 — Add credentials to `.env`



Edit **`/opt/rvu/.env`** on the production VM, or the local `.env` in `/Users/donnaile/dev/rvu/prod-rvu`.



Find these two blank lines and fill them in:



```env

SMTP_USER=noreply@midfloridasurgical.com   # the account from Step 1

SMTP_PASS=xxxx xxxx xxxx xxxx             # the 16-char App Password from Step 3

```



The other SMTP values are already set correctly:



```env

SMTP_HOST=smtp.gmail.com

SMTP_PORT=587

SMTP_FROM_NAME=Mid Florida Surgical

SMTP_ENABLED=true

```



If another practice app reuses the same module, add the same variables to that app’s `.env` as well.



---



## Step 5 — Restart the RVU API



```bash

sudo systemctl restart rvu-api

```



(Adjust the unit name if yours differs.)



---



## Step 6 — Test a live send



From the RVU portal (once logged in as admin), go to **Staff** and hit

**Send Magic Link** for any surgeon who has an email on file.



Or hit the API directly:



```bash

# First get an admin_token cookie via portal login, then:

curl -s -X POST https://rvu.midfloridasurgical.com/api/v1/auth/admin/send-magic-link \

  -H "Content-Type: application/json" \

  -b "admin_token=YOUR_TOKEN" \

  -d '{"surgeon_id": 1}'

```



A successful response looks like:



```json

{

  "ok": true,

  "surgeon": "Dr. Jane Smith",

  "email": "jsmith@midfloridasurgical.com",

  "magic_url": "https://rvu.midfloridasurgical.com/register?token=..."

}

```



The email arrives within seconds. It contains:



- A big **tap-to-open button** (works on any phone)

- An **embedded QR code** (for staff reading on a desktop who want to open on phone)

- A raw link fallback for copy/paste

- An expiry notice (default: 168 hours / 7 days)



---



## Troubleshooting



| Symptom | Fix |

|---------|-----|

| `SMTP_USER/SMTP_PASS not set` in logs | Fill in the two `.env` lines and restart |

| `SMTPAuthenticationError` | App Password is wrong or 2-Step Verification is off — redo Step 3 |

| `App passwords` menu missing | Google Workspace admin needs to enable it — see Step 3 note |

| Email goes to spam | Add an SPF record for `midfloridasurgical.com` that includes Google (`include:_spf.google.com`) — your domain DNS already has this if using Google Workspace MX |

| `surgeon has no email` error | Add the surgeon’s email in the **portal → Staff** screen (or directly in the `surgeons` table) |



---



## How it works (for reference)



```

Admin clicks "Send Magic Link"

        ↓

Backend generates a fresh one-time token (SHA-256 hashed, stored in magic_links table)

        ↓

email_service.py builds HTML email with embedded QR code (qrcode + Pillow)

        ↓

Sends via Gmail SMTP (port 587, STARTTLS) in background thread

        ↓

Staff taps link on phone → /register?token=...

        ↓

Token validated, SurgeonDevice row created, surgeon_token cookie set (365 days)

        ↓

Staff is in the app

```



The same `email_service.py` pattern can be copied into other apps:



```python

from app.email_service import send_magic_link_email



send_magic_link_email(

    to_email="surgeon@midfloridasurgical.com",

    to_name="Dr. Smith",

    magic_url="https://yourapp.midfloridasurgical.com/register?token=...",

    app_name="Your App Name",

)

```

