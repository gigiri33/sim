# -*- coding: utf-8 -*-
import os
from dotenv import load_dotenv

load_dotenv()

# ── Environment ────────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
DB_NAME   = os.getenv("DB_NAME", "configflow.db")

# ── Branding & External API URLs ───────────────────────────────────────────────
BRAND_TITLE          = "ConfigFlow"
DEFAULT_ADMIN_HANDLE = ""
CRYPTO_PRICES_API    = "https://swapwallet.app/api/v1/market/prices"
TETRAPAY_CREATE_URL  = "https://tetra98.com/api/create_order"
TETRAPAY_VERIFY_URL  = "https://tetra98.com/api/verify"
SWAPWALLET_BASE_URL  = "https://swapwallet.app/api"

# ── Admin Permission System ────────────────────────────────────────────────────
ADMIN_PERMS = [
    ("full",           "دسترسی کامل (مانند اونر)"),
    ("types_packages", "مدیریت نوع و پکیج‌ها"),
    ("register_config","ثبت کانفیگ"),
    ("view_configs",   "دیدن کانفیگ‌های ثبت‌شده"),
    ("manage_configs", "حذف و منقضی‌کردن کانفیگ‌ها"),
    ("broadcast_all",  "فوروارد همگانی"),
    ("broadcast_cust", "فوروارد برای مشتریان"),
    ("view_users",     "مدیریت کاربران (فقط مشاهده)"),
    ("agency",         "تایید/رد نمایندگی"),
    ("assign_config",  "ثبت کانفیگ برای کاربران"),
    ("manage_balance", "مدیریت موجودی کاربران"),
    ("user_status",    "تعیین امن/ناامن کاربران"),
    ("full_users",       "دسترسی کامل مدیریت کاربران"),
    ("settings",         "دسترسی به تنظیمات ربات"),
    ("approve_payments", "تایید یا رد پرداخت‌ها"),
    ("approve_renewal",  "تایید تمدید کردن"),
    ("manage_panels",    "مدیریت پنل‌های 3x-ui"),
]

# Custom emoji IDs for admin permission labels (icon_custom_emoji_id on buttons, ce() in HTML)
PERM_EMOJI_IDS = {
    "full":             "5210952531676504517",
    "types_packages":   "5463224921935082813",
    "register_config":  "5458799228719472718",
    "view_configs":     "5334882760735598374",
    "manage_configs":   "5424892643760937442",
    "broadcast_all":    "5416106115630918483",
    "broadcast_cust":   "5197304993920616826",
    "view_users":       "5372926953978341366",
    "agency":           "5357080225463149588",
    "assign_config":    "5812073100702914750",
    "manage_balance":   "5258134813302332906",
    "user_status":      "5375296873982604963",
    "full_users":       "5472308992514464048",
    "settings":         "5463036196777128277",
    "approve_payments": "5350396951407895212",
    "approve_renewal":  "6019455416201646359",
    "manage_panels":    "5372926953978341366",
}
PERM_FULL_SET = {
    "types_packages", "register_config", "view_configs", "manage_configs",
    "broadcast_all", "broadcast_cust", "view_users", "agency", "assign_config",
    "manage_balance", "user_status", "full_users", "settings",
    "approve_payments", "approve_renewal", "manage_panels",
}
PERM_USER_FULL = {"agency", "assign_config", "manage_balance", "user_status"}

# ── Crypto Configuration ───────────────────────────────────────────────────────
CRYPTO_API_SYMBOLS = {
    "tron":       "TRX",
    "usdt_trc20": "USDT",
    "usdt_bep20": "USDT",
    "usdt_ton":   "USDT",
    "usdc_bep20": "USDC",
    "eth":        "ETH",
    "btc":        "BTC",
    "bnb":        "BNB",
    "ton":        "TON",
    "sol":        "SOL",
    "ltc":        "LTC",
}

CRYPTO_COINS = [
    ("tron",       "ترون (TRC20)"),
    ("usdt_trc20", "تتر (TRC20)"),
    ("usdt_bep20", "تتر (BEP20)"),
    ("eth",        "اتریوم (ETH)"),
    ("btc",        "بیتکوین (BTC)"),
    ("bnb",        "بایننس‌کوین (BNB)"),
    ("usdc_bep20", "یو‌اس‌دی‌سی (BEP20)"),
    ("usdt_ton",   "تتر (TON)"),
    ("ton",        "تون (TON)"),
    ("sol",        "سولانا (SOL)"),
    ("ltc",        "لایت‌کوین (LTC)"),
]

# Custom emoji IDs for crypto coin labels
CRYPTO_EMOJI_IDS = {
    "tron":       "6028143164378845862",
    "usdt_trc20": "6028143164378845862",
    "usdt_bep20": "6028584717081645421",
    "usdt_ton":   "6030549140633555631",
    "usdc_bep20": "6030598017361383746",
    "eth":        "6030429096297632758",
    "btc":        "6030734193594470413",
    "bnb":        "6030374056291733605",
    "ton":        "6030549140633555631",
    "sol":        "6028283511025176940",
    "ltc":        "5796399747132563586",
}

# ── Pagination ─────────────────────────────────────────────────────────────────
CONFIGS_PER_PAGE = 10

# ── License System ─────────────────────────────────────────────────────────────
LICENSE_API_URL              = os.getenv("LICENSE_API_URL", "")
LICENSE_CHECK_INTERVAL       = int(os.getenv("LICENSE_CHECK_INTERVAL", "1800"))
LICENSE_NOTIFY_INTERVAL_MINUTES = int(os.getenv("LICENSE_NOTIFY_INTERVAL_MINUTES", "360"))
LICENSE_GRACE_MINUTES        = int(os.getenv("LICENSE_GRACE_MINUTES", "60"))

# ── Validation ─────────────────────────────────────────────────────────────────
if not BOT_TOKEN or ":" not in BOT_TOKEN:
    raise SystemExit("BOT_TOKEN تنظیم نشده یا معتبر نیست.")
if not ADMIN_IDS:
    raise SystemExit("ADMIN_IDS تنظیم نشده است.")
