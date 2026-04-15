# Seamless Iran Agent — Offline Install Guide

This directory contains everything needed to run the **Iran Agent** on an Iran VPS.
The agent connects to the bot API on the foreign server, sends heartbeats, and tests
your 3x-ui panel login.

> **Zero external dependencies.**  The agent uses only Python standard library
> (`urllib`, `http.cookiejar`, `json`, `logging`, …).  No `pip install`,
> no `apt install`, no internet access is required on the Iran server.

---

## Architecture

```
┌──────────────────────────┐          ┌───────────────────────────────┐
│   Iran Server             │          │   Foreign Server (Bot)        │
│                          │          │                               │
│  ┌──────────────────┐   │  HTTP(S)  │  ┌─────────────────────────┐ │
│  │  seamless-iran   │──────────────▶│  │  Bot API  /iran/*       │ │
│  │  agent           │   │          │  └─────────────────────────┘ │
│  └──────┬───────────┘   │          └───────────────────────────────┘
│         │               │
│  ┌──────▼───────────┐   │
│  │  3x-ui Panel     │   │
│  │  (local login)   │   │
│  └──────────────────┘   │
│                          │
│  (optional: Xray proxy)  │
└──────────────────────────┘
```

---

## Manual assets required before building iran.zip

> Do this ONCE on a machine that HAS internet access, then include the files in the bundle.

| File | Source | Place at |
|------|--------|----------|
| `xray` (Linux x86_64 binary) | [Xray-core releases](https://github.com/XTLS/Xray-core/releases) → `Xray-linux-64.zip` → extract `xray` | `iran/xray/xray` |

All other files are already in the bundle.  No Python wheels or apt packages are needed.

### How to download the Xray binary (on an internet-connected machine)

```bash
curl -L https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
     -o Xray-linux-64.zip
unzip -j Xray-linux-64.zip xray -d iran/xray/
chmod +x iran/xray/xray
```

> Only needed if you plan to use **xray_vless** outbound mode.
> For `direct` and `http_proxy` modes, no binary is needed.

---

## Building iran.zip

Run this once on your development machine (after placing any required assets):

```bash
# From the project root:
zip -r iran.zip iran/ -x "iran/__pycache__/*" -x "iran/**/*.pyc" -x "iran/.git/*"
```

Transfer `iran.zip` to the Iran server (e.g. via SCP):

```bash
scp iran.zip root@YOUR_IRAN_SERVER_IP:/root/
```

---

## Installation on the Iran server

```bash
# 1. Transfer and extract
scp iran.zip root@YOUR_IRAN_SERVER:/root/
ssh root@YOUR_IRAN_SERVER

# 2. Extract
unzip iran.zip
cd iran/

# 3. Run installer
sudo bash install.sh
```

The installer asks you a few questions and sets everything up.

---

## Mode 1 — direct

The agent connects directly to the foreign server.
No proxy, no Xray needed.

```
Choose mode (1/2/3): 1
```

Required inputs:
- Bot API Base URL (e.g. `http://1.2.3.4:8080`)
- Registration Token (from bot admin panel)
- 3x-ui panel credentials

---

## Mode 2 — http_proxy

The agent routes all outbound traffic through an existing HTTP proxy.

```
Choose mode (1/2/3): 2
Proxy URL: http://PROXY_IP:PORT
```

The proxy URL is written to `PROXY_URL=` in `config.env`.

---

## Mode 3 — xray_vless

The agent tunnels through a local Xray process running VLESS outbound.
Xray listens on `127.0.0.1:10809` (HTTP proxy) and the agent uses that.

**Requirements:**
- `iran/xray/xray` binary must be present in the bundle before building `iran.zip`

```
Choose mode (1/2/3): 3
VLESS URI: vless://UUID@host:port?security=reality&pbk=...&sid=...#name
```

The installer:
1. Checks `iran/xray/xray` exists — exits with a clear error if missing
2. Parses the VLESS URI (pure Python stdlib — no external lib)
3. Builds `/etc/xray/config.json` (HTTP inbound → VLESS outbound)
4. Installs `/usr/local/bin/xray` from the local binary
5. Creates and starts the `xray` systemd service
6. Sets `PROXY_URL=http://127.0.0.1:10809` in `config.env`

---

## What a successful installation looks like

```
[OK]   Python 3.10 found at /usr/bin/python3
[OK]   Bundled Xray binary found: /root/iran/xray/xray
[OK]   VLESS URI parsed and Xray config generated
[OK]   Binary installed
[OK]   xray service is running
[OK]   Files copied to /opt/seamless-iran-agent
[OK]   config.env written (mode: xray_vless)
[OK]   Registration successful!
[OK]   Panel login test passed!
[OK]   Service seamless-iran-agent is running
```

---

## Verification commands

```bash
# Agent status
systemctl status seamless-iran-agent
journalctl -u seamless-iran-agent -f

# Xray status (xray_vless mode only)
systemctl status xray
journalctl -u xray -f

# Health check
cd /opt/seamless-iran-agent
python3 healthcheck.py

# Manual panel test
python3 test_panel.py --local
```

---

## Troubleshooting

### Xray binary not found

```
ERROR: Local Xray binary not found.
Expected: iran/xray/xray
```

**Fix:** Download the Linux xray binary on a machine with internet access, place it
at `iran/xray/xray`, then rebuild `iran.zip`.

### Panel login failed

```
Panel login test FAILED: Cannot connect to panel at http://127.0.0.1:2053
```

**Checks:**
- Is 3x-ui running? `systemctl status x-ui`
- Correct port? Default is `2053`; check inside the 3x-ui panel settings
- Correct credentials in `/opt/seamless-iran-agent/config.env`

Re-test: `cd /opt/seamless-iran-agent && python3 test_panel.py --local`

### Registration failed

```
Registration FAILED.
```

**Checks:**
- Is the foreign Bot API reachable? `curl http://BOT_IP:8080/health`
- If using `xray_vless`: is Xray running? `systemctl status xray`
- Is the registration token correct and not yet used?
- Try: `journalctl -u xray -f` to see if VLESS tunnel is working

Re-run registration: `cd /opt/seamless-iran-agent && python3 register.py`

### Agent not sending heartbeats

```bash
journalctl -u seamless-iran-agent -f
```

Look for `Heartbeat FAILED` — this usually means the proxy / network is not working.

---

## File structure

```
iran/
├── install.sh               ← Offline installer (all 3 modes)
├── agent.py                 ← Main daemon
├── register.py              ← One-time registration script
├── healthcheck.py           ← Health check utility
├── test_panel.py            ← Panel login test utility
├── config.env.example       ← Config template
├── requirements.txt         ← Empty (stdlib only)
├── README.md                ← This file
├── lib/
│   ├── api_client.py        ← HTTP client (urllib, no requests)
│   ├── panel_client.py      ← 3x-ui login client (urllib, no requests)
│   ├── config_loader.py     ← Env file parser (no python-dotenv)
│   └── logger.py            ← Stdlib logging
├── xray/
│   ├── xray                 ← Linux binary (place here before building zip)
│   ├── parse_vless.py       ← VLESS URI parser
│   ├── build_xray_config.py ← Builds /etc/xray/config.json
│   ├── install_xray.sh      ← Copies binary + installs service
│   ├── README.md            ← How to get the xray binary
│   └── service/
│       └── xray.service     ← systemd unit for xray
└── service/
    └── seamless-iran-agent.service ← systemd unit template
```

│                          │          │                              │
│   ┌──────────────────┐   │  HTTPS   │  ┌────────────────────────┐  │
│   │  seamless-iran   │──────────────▶  │  Seamless Bot API      │  │
│   │  agent (this)    │   │          │  │  (Flask /iran/*)       │  │
│   └──────┬───────────┘   │          │  └────────────────────────┘  │
│          │               │          │                              │
│   ┌──────▼───────────┐   │          │                              │
│   │  3x-ui Panel     │   │          │                              │
│   │  (HTTP login)    │   │          │                              │
│   └──────────────────┘   │          │                              │
└──────────────────────────┘          └──────────────────────────────┘
```

- Agent روی سرور ایران اجرا می‌شود.
- هر چند ثانیه یک **Heartbeat** به API سرور خارج ارسال می‌کند.
- به‌طور دوره‌ای لاگین پنل 3x-ui را تست می‌کند و نتیجه را گزارش می‌دهد.
- Agent هرگز ارتباط ورودی نمی‌پذیرد — فقط خروجی دارد.

---

## نصب (خودکار)

```bash
curl -fsSL https://YOUR_CDN/iran-agent/install.sh | sudo bash
```

یا دستی:

```bash
sudo bash install.sh
```

اسکریپت تمام مراحل را به‌صورت تعاملی انجام می‌دهد:
1. بررسی Python 3
2. نصب وابستگی‌ها
3. دریافت پیکربندی از شما
4. ثبت‌نام خودکار با API ربات
5. تست لاگین پنل
6. نصب سرویس systemd

---

## نصب دستی

### 1. ایجاد توکن ثبت‌نام

در ربات تلگرام:
```
⚙️ پنل مدیریت → 🇮🇷 پنل‌های ثنایی (ایران) → 🔑 توکن‌های ثبت‌نام → ساخت توکن جدید
```
برچسب (مثلاً "Tehran-1") را وارد کنید. توکن ۲۴ ساعت اعتبار دارد.

### 2. کپی فایل‌ها

```bash
scp -r iran/ root@IRAN_SERVER_IP:/opt/seamless-iran-agent/
ssh root@IRAN_SERVER_IP
cd /opt/seamless-iran-agent
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 3. پیکربندی

```bash
cp config.env.example config.env
nano config.env
```

متغیرهای ضروری:

| متغیر | توضیح |
|-------|-------|
| `BOT_API_URL` | آدرس سرور خارج (مثلاً `http://1.2.3.4:8080`) |
| `REGISTRATION_TOKEN` | توکن دریافتی از ربات |
| `AGENT_NAME` | نام نمایشی این Agent |
| `PANEL_NAME` | نام نمایشی پنل |
| `PANEL_HOST` | آی‌پی یا دامنه پنل 3x-ui |
| `PANEL_PORT` | پورت پنل (پیش‌فرض `2053`) |
| `PANEL_PATH` | مسیر پنل (اگر خالی باشد `/` استفاده می‌شود) |
| `PANEL_USERNAME` | نام کاربری پنل |
| `PANEL_PASSWORD` | رمز عبور پنل |

### 4. ثبت‌نام

```bash
venv/bin/python register.py
```

پس از موفقیت، `AGENT_UUID` و `AGENT_SECRET` به‌صورت خودکار در `config.env` نوشته می‌شوند.

### 5. تست پنل

```bash
venv/bin/python test_panel.py --local   # فقط تست لاگین
venv/bin/python test_panel.py           # تست + گزارش به ربات
```

### 6. نصب سرویس systemd

```bash
cp service/seamless-iran-agent.service /etc/systemd/system/
# ویرایش WorkingDirectory و ExecStart اگر نصب در مسیر دیگری است
systemctl daemon-reload
systemctl enable seamless-iran-agent
systemctl start seamless-iran-agent
```

---

## مدیریت سرویس

```bash
# وضعیت
systemctl status seamless-iran-agent

# لاگ‌های زنده
journalctl -u seamless-iran-agent -f

# راه‌اندازی مجدد
systemctl restart seamless-iran-agent

# بررسی سلامت
venv/bin/python healthcheck.py
```

---

## ساختار فایل‌ها

```
iran/
├── agent.py           ← مین‌لوپ daemon
├── register.py        ← ثبت‌نام یک‌بار
├── test_panel.py      ← تست لاگین پنل
├── healthcheck.py     ← بررسی وضعیت کامل
├── install.sh         ← نصب تعاملی
├── requirements.txt
├── config.env.example
├── config.env         ← پیکربندی واقعی (بعد از نصب)
├── lib/
│   ├── api_client.py  ← ارتباط با API سرور خارج
│   ├── config_loader.py
│   ├── logger.py
│   └── panel_client.py ← تست لاگین 3x-ui
└── service/
    └── seamless-iran-agent.service
```

---

## امنیت

- `config.env` با مجوز `600` ذخیره می‌شود (فقط root).
- `AGENT_SECRET` هرگز در لاگ نوشته نمی‌شود.
- Agent از راه اینترنت قابل دسترس نیست — فقط ارتباط خروجی دارد.
- رمز عبور پنل روی سرور خارج رمزنگاری‌شده (Fernet) ذخیره می‌شود.

---

## رفع مشکل

### Agent ثبت‌نام نمی‌شود
- توکن ثبت‌نام را بررسی کنید (۲۴ ساعت اعتبار دارد).
- `BOT_API_URL` باید از سرور ایران قابل دسترس باشد.
- دیوار آتش سرور خارج پورت API را باز کرده باشد.

### لاگین پنل ناموفق
- آی‌پی، پورت، و مسیر پنل را بررسی کنید.
- مطمئن شوید سرویس 3x-ui در حال اجرا است.
- اگر پنل HTTPS دارد، مسیر را به‌درستی وارد کنید.

### Heartbeat قطع می‌شود
- لاگ را بررسی کنید: `journalctl -u seamless-iran-agent -n 50`
- اگر IP سرور خارج تغییر کرده، `BOT_API_URL` را به‌روز کنید.
