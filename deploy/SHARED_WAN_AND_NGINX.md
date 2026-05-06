# RVU on the same WAN IP as other practice sites (e.g. Atlas)

This file is nginx/TLS reference only. The canonical deploy sequence is `docs/DEPLOY_RUNBOOK.md`.

## Your layout

| Host / DNS | Typical WAN | Notes |
|------------|-------------|--------|
| **atlas.midfloridasurgical.com**, **rvu.midfloridasurgical.com**, and other vhosts on the same host | **50.192.210.75** | One public IP — **no extra address needed**. Browser sends **SNI** (hostname); nginx chooses the right `server { }` and TLS cert. |
| **aex.midfloridasurgical.com** (Aprima Explorer) | **50.192.210.77** | Different machine/IP — unrelated to RVU. |

One A record for `rvu` pointing at **50.192.210.75** is correct.

## What the reverse proxy is (on `.75`)

On this stack the edge is **nginx**, not Caddy. The repo contains a reference layout for the Atlas host: `sss/llm-gateway-updated.conf` (path on server is often `/etc/nginx/sites-enabled/llm-gateway` or similar).

That file defines **`listen 443 ssl http2 default_server`** for **atlas.midfloridasurgical.com**. Any HTTPS request whose **Host** does not match another `server_name` still hits that block — so nginx presents **Atlas’s certificate**. That is why `https://rvu.midfloridasurgical.com` failed before: DNS pointed at `.75`, but there was **no** dedicated `server` for `rvu`, so clients got **atlas’s** cert (name mismatch).

## Fix (on the **.75** server, as root)

1. **Run the RVU API** on localhost, e.g. Docker `rvu_api` → **127.0.0.1:3010** (or uvicorn per README).

2. **Install a certificate for RVU** (Let’s Encrypt):

   ```bash
   sudo certbot certonly --nginx -d rvu.midfloridasurgical.com
   ```

   If nginx has no `server_name rvu` yet, use webroot or standalone briefly, or add a minimal HTTP `server` first; easiest is often:

   ```bash
   sudo certbot certonly --webroot -w /var/www/html -d rvu.midfloridasurgical.com
   ```

   …only if you already serve `/.well-known` on port 80 for that host. Adjust to match your server.

3. **Enable the RVU vhost** — either:

   - **A)** Copy the full file:

     ```bash
     sudo cp /path/to/rvu/repo/deploy/nginx-rvu.conf /etc/nginx/sites-available/rvu
     sudo ln -sf /etc/nginx/sites-available/rvu /etc/nginx/sites-enabled/rvu
     ```

   - **B)** Or **paste** the two `server { ... }` blocks from `nginx-rvu.conf` into your combined site file (e.g. below the Atlas block, same style as `referral.midfloridasurgical.com` in `llm-gateway-updated.conf`).

4. **Check upstream port** in `nginx-rvu.conf`: `proxy_pass http://127.0.0.1:3010/;` must match where `rvu_api` listens.

5. **Reload nginx**

   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

6. **Verify TLS**

   ```bash
   echo | openssl s_client -connect rvu.midfloridasurgical.com:443 -servername rvu.midfloridasurgical.com 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName
   ```

   You should see **DNS:rvu.midfloridasurgical.com** in SANs.

7. **App env** (`.env` for `rvu_api`):

   - `BASE_URL=https://rvu.midfloridasurgical.com`
   - `RVU_COOKIE_SECURE=true`
   - `RVU_CORS_ORIGINS=https://rvu.midfloridasurgical.com`

## Summary

| Question | Answer |
|----------|--------|
| Who is the proxy? | **nginx** on the **50.192.210.75** host (with Atlas and other vhosts). |
| Caddy? | Not used for this hostname in-repo; AEX on **.77** may use different stack. |
| Why one IP works | **SNI**: multiple HTTPS hostnames on one IP, each with its own `server { }` + cert. |
| What was broken? | **`default_server` Atlas** vhost answered for `rvu` with the **wrong cert** until a **dedicated RVU** server block + cert existed. |
