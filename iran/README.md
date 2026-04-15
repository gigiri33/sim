# Seamless Iran Agent

این ابزار سرویس Iran Agent سیستم Seamless VPN است که روی **سرور ایران** اجرا می‌شود و پنل 3x-ui را به ربات اصلی متصل می‌کند.

---

## معماری

```
┌──────────────────────────┐          ┌──────────────────────────────┐
│   سرور ایران              │          │   سرور خارج                   │
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
