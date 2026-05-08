# -*- coding: utf-8 -*-
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta

import jdatetime

from .config import DB_NAME, CRYPTO_COINS
from .helpers import now_str, _TZ_TEHRAN


# ── Per-thread persistent connection ──────────────────────────────────────────
# Re-using one connection per OS thread (telebot uses a thread-pool) avoids the
# overhead of opening/closing a new file handle on every DB call.
_tls = threading.local()


def get_conn():
    conn = getattr(_tls, "conn", None)
    if conn is None:
        conn = sqlite3.connect(DB_NAME, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous  = NORMAL")   # safe with WAL, faster
        conn.execute("PRAGMA cache_size    = -8000")   # 8 MB page cache per conn
        conn.execute("PRAGMA busy_timeout  = 30000")   # wait up to 30s on write contention
        _tls.conn = conn
    return conn


# ── Settings in-process cache (TTL = 10 s) ────────────────────────────────────
# setting_get() is called on EVERY message/callback (bot_status, channel_id,
# gateway flags …).  Hitting SQLite for each of those adds up fast.
_SETTINGS_CACHE: dict[str, str]  = {}
_SETTINGS_CACHE_TS: float        = 0.0
_SETTINGS_CACHE_TTL: float       = 60.0   # seconds
_SETTINGS_LOCK                   = threading.Lock()


def _refresh_settings_cache(conn) -> None:
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    with _SETTINGS_LOCK:
        _SETTINGS_CACHE.clear()
        for r in rows:
            _SETTINGS_CACHE[r["key"]] = r["value"] or ""
        global _SETTINGS_CACHE_TS
        _SETTINGS_CACHE_TS = time.monotonic()


def _invalidate_settings_cache() -> None:
    """Call after any setting_set() so the next read re-fetches from DB."""
    global _SETTINGS_CACHE_TS
    with _SETTINGS_LOCK:
        _SETTINGS_CACHE_TS = 0.0


# ── Database Initialisation ────────────────────────────────────────────────────

def _rebuild_panels_if_legacy() -> None:
    """
    If the panels table was created with the old schema (column 'ip' instead of 'host'),
    rebuild it with the current schema before any other migrations run.
    This uses a fresh direct connection to avoid transaction conflicts.
    """
    import sqlite3 as _sq3
    _c = None
    try:
        _c = _sq3.connect(DB_NAME, timeout=60, check_same_thread=False)
        _c.execute("PRAGMA journal_mode = WAL")
        _c.execute("PRAGMA busy_timeout  = 60000")  # wait up to 60s if locked
        cols = {row[1] for row in _c.execute("PRAGMA table_info(panels)").fetchall()}
        if "ip" not in cols:
            return
        # Old schema detected — rebuild
        _c.executescript("""
            PRAGMA foreign_keys = OFF;
            BEGIN;
            CREATE TABLE IF NOT EXISTS _panels_new (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT    NOT NULL,
                protocol          TEXT    NOT NULL DEFAULT 'http',
                host              TEXT    NOT NULL DEFAULT '',
                port              INTEGER NOT NULL DEFAULT 80,
                path              TEXT    NOT NULL DEFAULT '',
                username          TEXT    NOT NULL DEFAULT '',
                password          TEXT    NOT NULL DEFAULT '',
                sub_url_base      TEXT    NOT NULL DEFAULT '',
                is_active         INTEGER NOT NULL DEFAULT 1,
                connection_status TEXT    NOT NULL DEFAULT 'unknown',
                last_checked_at   TEXT    NOT NULL DEFAULT '',
                last_error        TEXT    NOT NULL DEFAULT '',
                created_at        TEXT    NOT NULL DEFAULT '',
                updated_at        TEXT    NOT NULL DEFAULT ''
            );
            INSERT INTO _panels_new(id, name, protocol, host, port, path,
                username, password, sub_url_base, is_active, connection_status,
                last_checked_at, last_error, created_at, updated_at)
            SELECT
                id,
                COALESCE(name, ''),
                COALESCE(CASE WHEN typeof(protocol)='text' THEN protocol END, 'http'),
                COALESCE(CASE WHEN typeof(ip)='text'       THEN ip       END, ''),
                COALESCE(port, 80),
                COALESCE(CASE WHEN typeof(path)='text'     THEN path     END, ''),
                COALESCE(CASE WHEN typeof(username)='text' THEN username END, ''),
                COALESCE(CASE WHEN typeof(password)='text' THEN password END, ''),
                '',
                COALESCE(is_active, 1),
                'unknown', '', '', '', ''
            FROM panels;
            DROP TABLE panels;
            ALTER TABLE _panels_new RENAME TO panels;
            COMMIT;
            PRAGMA foreign_keys = ON;
        """)
    except Exception as _e:
        pass
    finally:
        if _c is not None:
            _c.close()


def init_db():
    import time as _time
    # Step 1: Fix legacy panels schema (ip → host) before any other migration
    _rebuild_panels_if_legacy()

    # Step 2: Run migrations with retry — on rapid systemd restarts the old
    # process may still be alive and holding a write-lock for a few seconds.
    # The dedicated init connection already waits up to 60 s internally;
    # these outer retries are an extra safety net.
    _MAX_INIT_TRIES = 5
    _INIT_DELAY     = 10  # seconds between retries
    for _attempt in range(1, _MAX_INIT_TRIES + 1):
        try:
            _run_init_db_migrations()
            return
        except Exception as _exc:
            if "database is locked" in str(_exc).lower() and _attempt < _MAX_INIT_TRIES:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "init_db: database locked, retry %d/%d…", _attempt, _MAX_INIT_TRIES
                )
                _time.sleep(_INIT_DELAY)
            else:
                raise


def _run_init_db_migrations():
    # Use a fresh dedicated connection (not the shared TLS one) so we can set
    # a long busy_timeout without affecting runtime queries, and to avoid any
    # lingering transaction state from the TLS connection.
    _init_conn = sqlite3.connect(DB_NAME, timeout=60, check_same_thread=False)
    _init_conn.row_factory = sqlite3.Row
    _init_conn.execute("PRAGMA journal_mode = WAL")
    _init_conn.execute("PRAGMA busy_timeout  = 60000")  # wait up to 60 s
    _init_conn.execute("PRAGMA synchronous   = NORMAL")
    try:
        conn = _init_conn
        # Run CREATE TABLE statements one by one inside a single write
        # transaction.  executescript() issues a COMMIT first (losing our
        # BEGIN IMMEDIATE), so we use individual execute() calls instead.
        # BEGIN IMMEDIATE acquires the write lock now, waiting up to
        # busy_timeout (60 s) if another writer is still active.
        conn.execute("BEGIN IMMEDIATE")
        for _sql in [
            """CREATE TABLE IF NOT EXISTS users (
                user_id      INTEGER PRIMARY KEY,
                full_name    TEXT,
                username     TEXT,
                balance      INTEGER NOT NULL DEFAULT 0,
                joined_at    TEXT    NOT NULL,
                last_seen_at TEXT    NOT NULL,
                first_start_notified INTEGER NOT NULL DEFAULT 0,
                status       TEXT    NOT NULL DEFAULT 'unsafe',
                is_agent     INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS config_types (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                is_active   INTEGER NOT NULL DEFAULT 1
            )""",
            """CREATE TABLE IF NOT EXISTS packages (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id       INTEGER NOT NULL,
                name          TEXT    NOT NULL,
                volume_gb     REAL    NOT NULL,
                duration_days INTEGER NOT NULL,
                price         INTEGER NOT NULL,
                active        INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY(type_id) REFERENCES config_types(id) ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS configs (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                type_id             INTEGER NOT NULL,
                package_id          INTEGER NOT NULL,
                service_name        TEXT    NOT NULL,
                config_text         TEXT    NOT NULL,
                inquiry_link        TEXT,
                created_at          TEXT    NOT NULL,
                reserved_payment_id INTEGER,
                sold_to             INTEGER,
                purchase_id         INTEGER,
                sold_at             TEXT,
                is_expired          INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(type_id)    REFERENCES config_types(id) ON DELETE CASCADE,
                FOREIGN KEY(package_id) REFERENCES packages(id)     ON DELETE CASCADE
            )""",
            """CREATE TABLE IF NOT EXISTS payments (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                kind            TEXT    NOT NULL,
                user_id         INTEGER NOT NULL,
                package_id      INTEGER,
                amount          INTEGER NOT NULL,
                payment_method  TEXT    NOT NULL,
                status          TEXT    NOT NULL,
                receipt_file_id TEXT,
                receipt_text    TEXT,
                admin_note      TEXT,
                created_at      TEXT    NOT NULL,
                approved_at     TEXT,
                config_id       INTEGER,
                crypto_coin     TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS purchases (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL,
                package_id     INTEGER NOT NULL,
                config_id      INTEGER NOT NULL,
                amount         INTEGER NOT NULL,
                payment_method TEXT    NOT NULL,
                created_at     TEXT    NOT NULL,
                is_test        INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS agency_prices (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                package_id INTEGER NOT NULL,
                price      INTEGER NOT NULL,
                UNIQUE(user_id, package_id)
            )""",
            """CREATE TABLE IF NOT EXISTS agency_price_config (
                user_id     INTEGER PRIMARY KEY,
                price_mode  TEXT NOT NULL DEFAULT 'package',
                global_type TEXT NOT NULL DEFAULT 'pct',
                global_val  INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS agency_type_discount (
                user_id        INTEGER NOT NULL,
                type_id        INTEGER NOT NULL,
                discount_type  TEXT NOT NULL DEFAULT 'pct',
                discount_value INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, type_id)
            )""",
            """CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS admin_users (
                user_id     INTEGER PRIMARY KEY,
                added_by    INTEGER NOT NULL,
                added_at    TEXT    NOT NULL,
                permissions TEXT    NOT NULL DEFAULT '{}'
            )""",
            """CREATE TABLE IF NOT EXISTS pending_orders (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id        INTEGER NOT NULL,
                package_id     INTEGER NOT NULL,
                payment_id     INTEGER,
                amount         INTEGER NOT NULL,
                payment_method TEXT    NOT NULL,
                created_at     TEXT    NOT NULL,
                status         TEXT    NOT NULL DEFAULT 'waiting'
            )""",
            """CREATE TABLE IF NOT EXISTS pinned_messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                text       TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS pinned_message_sends (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                pin_id     INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS referrals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referee_id  INTEGER NOT NULL UNIQUE,
                created_at  TEXT    NOT NULL,
                start_reward_given   INTEGER NOT NULL DEFAULT 0,
                purchase_reward_given INTEGER NOT NULL DEFAULT 0
            )""",
            """CREATE TABLE IF NOT EXISTS discount_codes (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                code              TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                discount_type     TEXT    NOT NULL DEFAULT 'pct',
                discount_value    INTEGER NOT NULL DEFAULT 0,
                max_uses_total    INTEGER NOT NULL DEFAULT 0,
                max_uses_per_user INTEGER NOT NULL DEFAULT 0,
                used_count        INTEGER NOT NULL DEFAULT 0,
                is_active         INTEGER NOT NULL DEFAULT 1,
                created_at        TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS discount_code_uses (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                code_id  INTEGER NOT NULL REFERENCES discount_codes(id) ON DELETE CASCADE,
                user_id  INTEGER NOT NULL,
                used_at  TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS voucher_batches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    NOT NULL,
                gift_type   TEXT    NOT NULL DEFAULT 'wallet',
                gift_amount INTEGER,
                package_id  INTEGER,
                total_count INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT    NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS voucher_codes (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id  INTEGER NOT NULL REFERENCES voucher_batches(id) ON DELETE CASCADE,
                code      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                is_used   INTEGER NOT NULL DEFAULT 0,
                used_by   INTEGER,
                used_at   TEXT
            )""",
        ]:
            conn.execute(_sql)


        defaults = {
            "support_username": "",
            "payment_card":     "",
            "payment_bank":     "",
            "payment_owner":    "",
            "gw_card_enabled":      "0",
            "gw_card_visibility":   "public",
            "gw_card_display_name": "",
            "gw_crypto_enabled":    "0",
            "gw_crypto_visibility": "public",
            "gw_crypto_display_name": "",
            "gw_tetrapay_enabled":    "0",
            "gw_tetrapay_visibility": "public",
            "gw_tetrapay_display_name": "",
            "tetrapay_api_key":       "",
            "tetrapay_mode_bot":      "1",
            "tetrapay_mode_web":      "1",
            "gw_card_range_enabled":       "0",
            "gw_card_range_min":           "",
            "gw_card_range_max":           "",
            "gw_card_random_amount":        "0",
            "gw_crypto_range_enabled":     "0",
            "gw_crypto_range_min":         "",
            "gw_crypto_range_max":         "",
            "gw_tetrapay_range_enabled":   "0",
            "gw_tetrapay_range_min":       "",
            "gw_tetrapay_range_max":       "",
            "gw_swapwallet_crypto_enabled":    "0",
            "gw_swapwallet_crypto_visibility": "public",
            "gw_swapwallet_crypto_display_name": "",
            "gw_swapwallet_crypto_range_enabled": "0",
            "gw_swapwallet_crypto_range_min":     "",
            "gw_swapwallet_crypto_range_max":     "",
            "swapwallet_crypto_api_key":  "",
            "swapwallet_crypto_username": "",
            "swapwallet_active_currencies": "TRON,TON,BSC",
            "gw_tronpays_rial_display_name": "",
            "shop_open":         "1",
            "preorder_mode":     "0",
            "panel_renewal_enabled": "1",
            "support_link":        "",
            "support_link_desc":   "",
            "support_faq_enabled": "1",
            "support_faq_text":    "",
            "start_text":       "",
            "start_prefix_emoji": "",
            "start_photo_file_id": "",
            "channel_id":       "",
            "backup_enabled":   "0",
            "backup_interval":  "1440",
            "backup_target_id": "",
            "free_test_mode":    "everyone",
            "free_test_enabled": "1",
            "agent_test_limit": "0",
            "agent_test_period": "day",
            "phone_mode":        "disabled",
            "phone_iran_only":   "0",
            "purchase_rules_enabled": "0",
            "purchase_rules_text": "♨️ قوانین استفاده از خدمات ما\n\nلطفاً پیش از استفاده از سرویس‌ها، موارد زیر را با دقت مطالعه فرمایید:\n\n1️⃣ اطلاعیه‌های منتشرشده در کانال را حتماً دنبال کنید.\n\n2️⃣ در صورتی که با مشکلی در اتصال مواجه شدید، به پشتیبانی پیام دهید.\n\n3️⃣ از ارسال مشخصات سرویس از طریق پیامک خودداری کنید.\n\n4️⃣ مسئولیت حفظ اطلاعات سرویس بر عهده کاربر می‌باشد.\n\n5️⃣ هرگونه سوءاستفاده ممکن است منجر به مسدود شدن سرویس شود.",
            "group_id":                    "",
            "group_topic_backup":           "",
            "group_topic_new_users":        "",
            "group_topic_payment_approval": "",
            "group_topic_renewal_request":  "",
            "group_topic_purchase_log":     "",
            "group_topic_renewal_log":      "",
            "group_topic_wallet_log":       "",
            "group_topic_gateway_payment_log": "",
            "group_topic_test_report":      "",
            "group_topic_broadcast_report": "",
            "group_topic_error_log":        "",
            "agency_request_enabled":       "1",
            "agency_default_discount_pct":  "0",
            "referral_enabled":             "1",
            "referral_banner_text":         "",
            "referral_banner_photo":        "",
            "referral_start_reward_enabled":  "0",
            "referral_start_reward_count":    "1",
            "referral_start_reward_type":     "wallet",
            "referral_start_reward_amount":   "0",
            "referral_start_reward_package":  "",
            "referral_purchase_reward_enabled": "0",
            "referral_purchase_reward_count":   "1",
            "referral_purchase_reward_type":    "wallet",
            "referral_purchase_reward_amount":  "0",
            "referral_purchase_reward_package": "",
            "referral_reward_condition":         "channel",
            "locked_channels_list":              "[]",
            "discount_codes_enabled":             "1",
            "vouchers_enabled":                   "1",
            "bulk_sale_mode":                     "everyone",
            "bulk_min_qty":                       "1",
            "bulk_max_qty":                       "0",
            # ── Referral Anti-Spam ─────────────────────────────────────────────
            "referral_antispam_enabled":    "1",
            "referral_antispam_window":     "15",
            "referral_antispam_threshold":  "10",
            "referral_antispam_action":     "report_only",
            # ── Referral Captcha ───────────────────────────────────────────────
            "referral_captcha_enabled":     "1",
            # ── Referral Button Title ──────────────────────────────────────────
            "referral_button_title":         "",
            # ── Referral Invitee Reward ────────────────────────────────────────
            "ref_invitee_reward_enabled":    "0",
            "ref_invitee_reward_type":       "wallet",
            "ref_invitee_reward_amount":     "0",
            "ref_invitee_reward_package_id": "",
            # ── Payment Card Management ────────────────────────────────────────
            "gw_card_rotation_enabled":     "0",
            # ── Gateway Fee / Bonus ────────────────────────────────────────────
            "gw_card_fee_enabled":               "0",
            "gw_card_fee_type":                  "fixed",
            "gw_card_fee_value":                 "0",
            "gw_card_bonus_enabled":             "0",
            "gw_card_bonus_type":                "fixed",
            "gw_card_bonus_value":               "0",
            "gw_crypto_fee_enabled":             "0",
            "gw_crypto_fee_type":                "fixed",
            "gw_crypto_fee_value":               "0",
            "gw_crypto_bonus_enabled":           "0",
            "gw_crypto_bonus_type":              "fixed",
            "gw_crypto_bonus_value":             "0",
            "gw_tetrapay_fee_enabled":           "0",
            "gw_tetrapay_fee_type":              "fixed",
            "gw_tetrapay_fee_value":             "0",
            "gw_tetrapay_bonus_enabled":         "0",
            "gw_tetrapay_bonus_type":            "fixed",
            "gw_tetrapay_bonus_value":           "0",
            "gw_swapwallet_crypto_fee_enabled":  "0",
            "gw_swapwallet_crypto_fee_type":     "fixed",
            "gw_swapwallet_crypto_fee_value":    "0",
            "gw_swapwallet_crypto_bonus_enabled":"0",
            "gw_swapwallet_crypto_bonus_type":   "fixed",
            "gw_swapwallet_crypto_bonus_value":  "0",
            "gw_tronpays_rial_fee_enabled":      "0",
            "gw_tronpays_rial_fee_type":         "fixed",
            "gw_tronpays_rial_fee_value":        "0",
            "gw_tronpays_rial_bonus_enabled":    "0",
            "gw_tronpays_rial_bonus_type":       "fixed",
            "gw_tronpays_rial_bonus_value":      "0",
            # ── Tronado gateway ────────────────────────────────────────────────
            "gw_tronado_enabled":        "0",
            "gw_tronado_visibility":     "public",
            "gw_tronado_display_name":   "درگاه کارت به کارت (Tronado)",
            "gw_tronado_range_enabled":  "0",
            "gw_tronado_range_min":      "",
            "gw_tronado_range_max":      "",
            "gw_tronado_fee_enabled":    "0",
            "gw_tronado_fee_type":       "fixed",
            "gw_tronado_fee_value":      "0",
            "gw_tronado_bonus_enabled":  "0",
            "gw_tronado_bonus_type":     "fixed",
            "gw_tronado_bonus_value":    "0",
            "tronado_api_key":           "",
            "tronado_api_base_url":      "https://bot.tronado.cloud/api/v3",
            "tronado_wallet_address":    "",
            "tronado_callback_url":      "",
            # ── CentralPay gateway ─────────────────────────────────────────────
            "gw_centralpay_enabled":        "0",
            "gw_centralpay_visibility":     "public",
            "gw_centralpay_display_name":   "",
            "gw_centralpay_range_enabled":  "0",
            "gw_centralpay_range_min":      "",
            "gw_centralpay_range_max":      "",
            "gw_centralpay_fee_enabled":    "0",
            "gw_centralpay_fee_type":       "fixed",
            "gw_centralpay_fee_value":      "0",
            "gw_centralpay_bonus_enabled":  "0",
            "gw_centralpay_bonus_type":     "fixed",
            "gw_centralpay_bonus_value":    "0",
            "centralpay_api_key":                 "",
            "centralpay_getlink_url":             "https://centralapi.org/webservice/basic/getLink.php",
            "centralpay_verify_url":              "https://centralapi.org/webservice/basic/verify.php",
            "centralpay_callback_base_url":       "",
            "centralpay_link_type":               "deposit",
            # ── RialPay gateway ────────────────────────────────────────────────
            "gw_rialpay_enabled":                 "0",
            "gw_rialpay_visibility":              "public",
            "gw_rialpay_display_name":            "",
            "gw_rialpay_range_enabled":           "0",
            "gw_rialpay_range_min":               "",
            "gw_rialpay_range_max":               "",
            "gw_rialpay_fee_enabled":             "0",
            "gw_rialpay_fee_type":                "fixed",
            "gw_rialpay_fee_value":               "0",
            "gw_rialpay_bonus_enabled":           "0",
            "gw_rialpay_bonus_type":              "fixed",
            "gw_rialpay_bonus_value":             "0",
            "rialpay_api_key":                    "",
            "rialpay_webhook_secret":             "",
            "rialpay_create_invoice_url":         "https://rialbotapi.shop/api/create_invoice.php",
            "rialpay_check_invoice_url":          "https://rialbotapi.shop/api/invoicetest.php",
            "rialpay_callback_base_url":          "",
            # ── Invoice expiration ───────────────────────────────────────────
            "invoice_expiry_enabled":             "1",
            "invoice_expiry_minutes":             "30",
            # ── Tariff ────────────────────────────────────────────────────────
            "tariff_enabled":                     "1",
            "tariff_text":                        "",
            # ── Apps / Tutorial section ───────────────────────────────────────
            "apps_enabled":                       "1",
            # ── Start menu layout / button texts ──────────────────────────────
            "show_account_button":                "1",
            "start_menu_layout":                  "[[\"buy_service\",\"my_services\"],[\"free_test\"],[\"wallet\",\"account\"],[\"voucher\",\"referral\"],[\"tariff\",\"apps\"],[\"support\"],[\"agency\"],[\"admin_panel\"]]",
            "start_menu_text:wallet":             "کیف پول",
            "start_menu_text:apps":               "دریافت اپلیکیشن‌ها",
            "start_menu_text:tariff":             "تعرفه",
            "start_menu_enabled:wallet":          "1",
            "start_menu_style:buy_service":       "primary",
            "start_menu_style:my_services":       "success",
        }
        for coin, _ in CRYPTO_COINS:
            defaults[f"crypto_{coin}"] = ""

        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v)
            )

        migrations = [
            "ALTER TABLE users ADD COLUMN first_start_notified INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN status TEXT NOT NULL DEFAULT 'safe'",
            "ALTER TABLE users ADD COLUMN is_agent INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE configs ADD COLUMN is_expired INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE payments ADD COLUMN crypto_coin TEXT",
            "ALTER TABLE packages ADD COLUMN position INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE config_types ADD COLUMN description TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE config_types ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE config_types ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
            "CREATE TABLE IF NOT EXISTS pinned_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS pinned_message_sends (id INTEGER PRIMARY KEY AUTOINCREMENT, pin_id INTEGER NOT NULL, user_id INTEGER NOT NULL, message_id INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS referrals (id INTEGER PRIMARY KEY AUTOINCREMENT, referrer_id INTEGER NOT NULL, referee_id INTEGER NOT NULL UNIQUE, created_at TEXT NOT NULL, start_reward_given INTEGER NOT NULL DEFAULT 0, purchase_reward_given INTEGER NOT NULL DEFAULT 0)",
            "CREATE TABLE IF NOT EXISTS agency_request_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, referee_uid INTEGER NOT NULL, chat_id INTEGER NOT NULL, message_id INTEGER NOT NULL)",
            "CREATE TABLE IF NOT EXISTS payment_admin_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, payment_id INTEGER NOT NULL, admin_id INTEGER NOT NULL, message_id INTEGER NOT NULL)",
            "ALTER TABLE packages ADD COLUMN show_name INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE packages ADD COLUMN max_users INTEGER NOT NULL DEFAULT 0",
            "CREATE TABLE IF NOT EXISTS discount_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE COLLATE NOCASE, discount_type TEXT NOT NULL DEFAULT 'pct', discount_value INTEGER NOT NULL DEFAULT 0, max_uses_total INTEGER NOT NULL DEFAULT 0, max_uses_per_user INTEGER NOT NULL DEFAULT 0, used_count INTEGER NOT NULL DEFAULT 0, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS discount_code_uses (id INTEGER PRIMARY KEY AUTOINCREMENT, code_id INTEGER NOT NULL REFERENCES discount_codes(id) ON DELETE CASCADE, user_id INTEGER NOT NULL, used_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS voucher_batches (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, gift_type TEXT NOT NULL DEFAULT 'wallet', gift_amount INTEGER, package_id INTEGER, total_count INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS voucher_codes (id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER NOT NULL REFERENCES voucher_batches(id) ON DELETE CASCADE, code TEXT NOT NULL UNIQUE COLLATE NOCASE, is_used INTEGER NOT NULL DEFAULT 0, used_by INTEGER, used_at TEXT)",
            "ALTER TABLE payments ADD COLUMN final_amount INTEGER",
            "ALTER TABLE payments ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE pending_orders ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE referrals ADD COLUMN channel_joined INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE referrals ADD COLUMN rewarded_at TEXT",
            "ALTER TABLE users ADD COLUMN phone_number TEXT",
            # audience: 'all' | 'public' | 'agents'  (default 'all' = everyone)
            "ALTER TABLE discount_codes ADD COLUMN audience TEXT NOT NULL DEFAULT 'all'",
            # scope_type: 'all' | 'types' | 'packages'
            "ALTER TABLE discount_codes ADD COLUMN scope_type TEXT NOT NULL DEFAULT 'all'",
            "CREATE TABLE IF NOT EXISTS discount_code_targets (id INTEGER PRIMARY KEY AUTOINCREMENT, code_id INTEGER NOT NULL REFERENCES discount_codes(id) ON DELETE CASCADE, target_type TEXT NOT NULL, target_id INTEGER NOT NULL, UNIQUE(code_id, target_type, target_id))",
            # buyer_role: 'all' | 'agents' | 'public'  (who can purchase this package)
            "ALTER TABLE packages ADD COLUMN buyer_role TEXT NOT NULL DEFAULT 'all'",
            # ── License system settings migration ──────────────────────────────
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_state','inactive')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_api_key','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_api_url_base','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_expires_at','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_machine_id','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_last_check','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_last_notify','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_owner_telegram_id','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_owner_username','')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('license_bot_username','')",
            # ── Pending Rewards (referral claim system) ────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS pending_rewards ("
                "id          INTEGER PRIMARY KEY AUTOINCREMENT,"
                "user_id     INTEGER NOT NULL,"
                "reward_type TEXT    NOT NULL DEFAULT 'wallet',"
                "amount      INTEGER NOT NULL DEFAULT 0,"
                "package_id  INTEGER,"
                "source      TEXT    NOT NULL DEFAULT 'start',"
                "claimed     INTEGER NOT NULL DEFAULT 0,"
                "created_at  TEXT    NOT NULL,"
                "claimed_at  TEXT"
                ")"
            ),
            # ── Locked channels list (multi-channel support) ──────────────────
            (
                "CREATE TABLE IF NOT EXISTS locked_channels ("
                "id         INTEGER PRIMARY KEY AUTOINCREMENT,"
                "channel_id TEXT    NOT NULL UNIQUE,"
                "added_at   TEXT    NOT NULL"
                ")"
            ),
            (
                "CREATE TABLE IF NOT EXISTS wallet_pay_exceptions ("
                "id       INTEGER PRIMARY KEY AUTOINCREMENT,"
                "user_id  INTEGER NOT NULL UNIQUE,"
                "added_at TEXT    NOT NULL"
                ")"
            ),
            # ── Panels (3x-ui / Sanaei) ───────────────────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS panels ("
                "id                INTEGER PRIMARY KEY AUTOINCREMENT,"
                "name              TEXT    NOT NULL,"
                "protocol          TEXT    NOT NULL DEFAULT 'http',"
                "host              TEXT    NOT NULL,"
                "port              INTEGER NOT NULL,"
                "path              TEXT    NOT NULL DEFAULT '',"
                "username          TEXT    NOT NULL,"
                "password          TEXT    NOT NULL,"
                "sub_url_base      TEXT    NOT NULL DEFAULT '',"
                "is_active         INTEGER NOT NULL DEFAULT 1,"
                "connection_status TEXT    NOT NULL DEFAULT 'unknown',"
                "last_checked_at   TEXT    NOT NULL DEFAULT '',"
                "last_error        TEXT    NOT NULL DEFAULT '',"
                "created_at        TEXT    NOT NULL,"
                "updated_at        TEXT    NOT NULL"
                ")"
            ),
            # ── Panels: add missing columns for older DBs ─────────────────────
            "ALTER TABLE panels ADD COLUMN protocol          TEXT    NOT NULL DEFAULT 'http'",
            "ALTER TABLE panels ADD COLUMN host              TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN port              INTEGER NOT NULL DEFAULT 80",
            "ALTER TABLE panels ADD COLUMN path              TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN username          TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN password          TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN is_active         INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE panels ADD COLUMN connection_status TEXT    NOT NULL DEFAULT 'unknown'",
            "ALTER TABLE panels ADD COLUMN last_checked_at   TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN last_error        TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN created_at        TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN updated_at        TEXT    NOT NULL DEFAULT ''",
            "ALTER TABLE panels ADD COLUMN sub_url_base      TEXT    NOT NULL DEFAULT ''",
            # ── Packages: panel-based config source ───────────────────────────
            "ALTER TABLE packages ADD COLUMN config_source TEXT NOT NULL DEFAULT 'manual'",
            "ALTER TABLE packages ADD COLUMN panel_id           INTEGER",
            "ALTER TABLE packages ADD COLUMN panel_type         TEXT",
            "ALTER TABLE packages ADD COLUMN panel_port         INTEGER",
            "ALTER TABLE packages ADD COLUMN delivery_mode      TEXT NOT NULL DEFAULT 'config_only'",
            "ALTER TABLE packages ADD COLUMN client_package_id  INTEGER",
            "ALTER TABLE panel_configs ADD COLUMN inbound_remark TEXT NOT NULL DEFAULT ''",
            # ── Panel Client Packages (config templates per panel/inbound) ────
            (
                "CREATE TABLE IF NOT EXISTS panel_client_packages ("
                "id             INTEGER PRIMARY KEY AUTOINCREMENT,"
                "panel_id       INTEGER NOT NULL,"
                "inbound_id     INTEGER NOT NULL,"
                "delivery_mode  TEXT    NOT NULL DEFAULT 'config_only',"
                "sample_config  TEXT    NOT NULL DEFAULT '',"
                "sample_sub_url TEXT    NOT NULL DEFAULT '',"
                "name           TEXT    NOT NULL DEFAULT '',"
                "created_at     TEXT    NOT NULL"
                ")"
            ),
            # ── Panel configs (auto-created by purchase) ──────────────────────
            (
                "CREATE TABLE IF NOT EXISTS panel_configs ("
                "id                 INTEGER PRIMARY KEY AUTOINCREMENT,"
                "user_id            INTEGER NOT NULL,"
                "package_id         INTEGER NOT NULL,"
                "panel_id           INTEGER NOT NULL,"
                "panel_type         TEXT    NOT NULL DEFAULT 'sanaei',"
                "inbound_id         INTEGER,"
                "inbound_port       INTEGER,"
                "client_name        TEXT,"
                "client_uuid        TEXT,"
                "client_sub_url     TEXT,"
                "client_config_text TEXT,"
                "inbound_remark     TEXT    NOT NULL DEFAULT '',"
                "expire_at          TEXT,"
                "is_expired         INTEGER NOT NULL DEFAULT 0,"
                "expired_notified   INTEGER NOT NULL DEFAULT 0,"
                "created_at         TEXT    NOT NULL,"
                "purchase_id        INTEGER,"
                "payment_id         INTEGER"
                ")"
            ),
            # ── User timed restriction ────────────────────────────────────────
            "ALTER TABLE users ADD COLUMN restricted_until INTEGER NOT NULL DEFAULT 0",
            # ── Panel template: client name used in the sample config fragment ─
            "ALTER TABLE panel_client_packages ADD COLUMN sample_client_name TEXT NOT NULL DEFAULT ''",
            # ── Panel configs: track which template (cpkg) was used ───────────
            "ALTER TABLE panel_configs ADD COLUMN cpkg_id INTEGER",
            # ── Panel configs: auto-renew and temporary-disable flags ─────────
            "ALTER TABLE panel_configs ADD COLUMN auto_renew   INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE panel_configs ADD COLUMN is_disabled  INTEGER NOT NULL DEFAULT 0",
            # ── Referral Anti-Spam Tables ──────────────────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS referral_restrictions ("
                "id              INTEGER PRIMARY KEY AUTOINCREMENT,"
                "user_id         INTEGER NOT NULL UNIQUE,"
                "restriction_type TEXT NOT NULL DEFAULT 'referral_only',"
                "reason          TEXT NOT NULL DEFAULT '',"
                "added_by        INTEGER NOT NULL DEFAULT 0,"
                "added_at        TEXT NOT NULL"
                ")"
            ),
            (
                "CREATE TABLE IF NOT EXISTS referral_spam_events ("
                "id           INTEGER PRIMARY KEY AUTOINCREMENT,"
                "user_id      INTEGER NOT NULL UNIQUE,"
                "notified_at  TEXT NOT NULL,"
                "action_taken TEXT NOT NULL DEFAULT ''"
                ")"
            ),
            # ── Payment Cards (multi-card management) ─────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS payment_cards ("
                "id          INTEGER PRIMARY KEY AUTOINCREMENT,"
                "card_number TEXT    NOT NULL,"
                "bank_name   TEXT    NOT NULL DEFAULT '',"
                "holder_name TEXT    NOT NULL DEFAULT '',"
                "is_active   INTEGER NOT NULL DEFAULT 1,"
                "created_at  TEXT    NOT NULL"
                ")"
            ),
            # ── Crypto comment code shown to user during payment ──────────────
            "ALTER TABLE payments ADD COLUMN crypto_comment TEXT",
            # ── Stored crypto equivalent amount at time of payment ────────────
            "ALTER TABLE payments ADD COLUMN crypto_amount TEXT",
            # ── Referral captcha verification tracking ────────────────────────
            "ALTER TABLE referrals ADD COLUMN captcha_verified INTEGER NOT NULL DEFAULT 0",
            # ── Referral captcha failure tracking ─────────────────────────────
            "ALTER TABLE referrals ADD COLUMN captcha_failed INTEGER NOT NULL DEFAULT 0",
            # ── Invitee reward tracking ────────────────────────────────────────
            "ALTER TABLE referrals ADD COLUMN invitee_reward_claimed INTEGER NOT NULL DEFAULT 0",
            # ── Reseller per-GB pricing ────────────────────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS reseller_per_gb_prices ("
                "id         INTEGER PRIMARY KEY AUTOINCREMENT,"
                "user_id    INTEGER NOT NULL,"
                "type_id    INTEGER NOT NULL,"
                "price_per_gb INTEGER NOT NULL,"
                "created_at TEXT NOT NULL,"
                "updated_at TEXT NOT NULL,"
                "UNIQUE(user_id, type_id)"
                ")"
            ),
            # ── Reseller requests table ────────────────────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS reseller_requests ("
                "id          INTEGER PRIMARY KEY AUTOINCREMENT,"
                "user_id     INTEGER NOT NULL,"
                "username    TEXT,"
                "full_name   TEXT,"
                "description TEXT,"
                "status      TEXT NOT NULL DEFAULT 'pending',"
                "rejected_at TEXT,"
                "reviewed_at TEXT,"
                "reviewed_by INTEGER,"
                "created_at  TEXT NOT NULL,"
                "updated_at  TEXT NOT NULL"
                ")"
            ),
            # ── Purchase credit on users table ────────────────────────────────
            "ALTER TABLE users ADD COLUMN purchase_credit_enabled INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE users ADD COLUMN purchase_credit_limit INTEGER NOT NULL DEFAULT 0",
            # ── Purchase addon prices ─────────────────────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS purchase_addon_prices ("
                "id                   INTEGER PRIMARY KEY AUTOINCREMENT,"
                "type_id              INTEGER NOT NULL,"
                "addon_type           TEXT    NOT NULL,"
                "normal_unit_price    INTEGER,"
                "reseller_unit_price  INTEGER,"
                "created_at           TEXT    NOT NULL,"
                "updated_at           TEXT    NOT NULL,"
                "UNIQUE(type_id, addon_type)"
                ")"
            ),
            "INSERT OR IGNORE INTO settings(key,value) VALUES('addon_volume_enabled','1')",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('addon_time_enabled','1')",
            # ── Discount code usage scope ─────────────────────────────────────
            "ALTER TABLE discount_codes ADD COLUMN usage_scope TEXT NOT NULL DEFAULT 'all'",
            # ── Admin balance adjustment tracking ─────────────────────────────
            "ALTER TABLE users ADD COLUMN total_admin_adjusted INTEGER NOT NULL DEFAULT 0",
            # ── Service naming for panel configs ──────────────────────────────
            "ALTER TABLE payments ADD COLUMN service_names_json TEXT",
            "INSERT OR IGNORE INTO settings(key,value) VALUES('panel_renewal_enabled','1')",
            "ALTER TABLE panel_configs ADD COLUMN is_test INTEGER NOT NULL DEFAULT 0",
            # ── Tronado idempotency + audit columns ───────────────────────────
            "ALTER TABLE payments ADD COLUMN gateway_ref TEXT",
            "ALTER TABLE payments ADD COLUMN external_txid TEXT",
            "ALTER TABLE payments ADD COLUMN raw_callback TEXT",
            "ALTER TABLE payments ADD COLUMN callback_received_at TEXT",
            "ALTER TABLE payments ADD COLUMN fulfilled_at TEXT",
            "ALTER TABLE payments ADD COLUMN expires_at TEXT",
            "ALTER TABLE payments ADD COLUMN notify_message_id INTEGER",
            "ALTER TABLE payments ADD COLUMN used_card_id INTEGER",
            # ── Config types: emoji and button color ──────────────────────────
            "ALTER TABLE config_types ADD COLUMN emoji TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE config_types ADD COLUMN button_color TEXT NOT NULL DEFAULT 'glass'",
            # ── Config types: purchase mode and invoice description ────────────
            "ALTER TABLE config_types ADD COLUMN purchase_mode TEXT NOT NULL DEFAULT 'step'",
            "ALTER TABLE config_types ADD COLUMN invoice_description TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE config_types ADD COLUMN glass_enabled_dims TEXT NOT NULL DEFAULT 'v,d,u,q'",
            # ── Glass buy: max order quantity setting ─────────────────────────
            "INSERT OR IGNORE INTO settings(key,value) VALUES('max_order_quantity','10')",
            # ── Support methods table ──────────────────────────────────────────
            (
                "CREATE TABLE IF NOT EXISTS support_methods ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " title TEXT NOT NULL,"
                " emoji TEXT NOT NULL DEFAULT '',"
                " color TEXT NOT NULL DEFAULT 'default',"
                " url TEXT NOT NULL,"
                " enabled INTEGER NOT NULL DEFAULT 1,"
                " sort_order INTEGER NOT NULL DEFAULT 0,"
                " created_at TEXT NOT NULL DEFAULT '',"
                " updated_at TEXT NOT NULL DEFAULT ''"
                ")"
            ),
            # ── Packages: per-package button color ────────────────────────────
            "ALTER TABLE packages ADD COLUMN button_color TEXT NOT NULL DEFAULT 'glass'",
            # ── Panel configs: inbound protocol (vmess/vless/trojan) ──────────
            "ALTER TABLE panel_configs ADD COLUMN inbound_protocol TEXT NOT NULL DEFAULT ''",
            # ── Panel configs: canonical delivery slot for idempotent bulk delivery ─
            "ALTER TABLE panel_configs ADD COLUMN delivery_slot_index INTEGER",
            # ── Persistent panel-config delivery queue ─────────────────────────
            """CREATE TABLE IF NOT EXISTS delivery_queue (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                chat_id         INTEGER NOT NULL,
                package_id      INTEGER NOT NULL,
                payment_id      INTEGER NOT NULL,
                slot_index      INTEGER,
                desired_name    TEXT,
                unit_price      INTEGER NOT NULL DEFAULT 0,
                payment_method  TEXT    NOT NULL DEFAULT '',
                is_test         INTEGER NOT NULL DEFAULT 0,
                status          TEXT    NOT NULL DEFAULT 'pending',
                retry_count     INTEGER NOT NULL DEFAULT 0,
                last_error      TEXT,
                next_retry_at   TEXT,
                created_at      TEXT    NOT NULL,
                delivered_at    TEXT,
                panel_config_id INTEGER,
                client_uuid     TEXT,
                client_name     TEXT
            )""",
            "ALTER TABLE delivery_queue ADD COLUMN slot_index INTEGER",
            # ── Canonical panel delivery slots ────────────────────────────────
            """CREATE TABLE IF NOT EXISTS delivery_slots (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id      INTEGER NOT NULL,
                user_id         INTEGER NOT NULL,
                package_id      INTEGER NOT NULL,
                slot_index      INTEGER NOT NULL,
                desired_name    TEXT,
                status          TEXT    NOT NULL DEFAULT 'pending',
                panel_config_id INTEGER,
                queue_id        INTEGER,
                last_error      TEXT,
                created_at      TEXT,
                updated_at      TEXT,
                UNIQUE(payment_id, slot_index)
            )""",
            # ── Locked channels: optional invite link for private channels ─────
            "ALTER TABLE locked_channels ADD COLUMN join_url TEXT NOT NULL DEFAULT ''",
        ]
        for sql in migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass

        # ── Indexes (CREATE IF NOT EXISTS is idempotent) ───────────────────────
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_configs_pkg_avail   ON configs(package_id) WHERE sold_to IS NULL AND is_expired=0",
            "CREATE INDEX IF NOT EXISTS idx_configs_sold_to      ON configs(sold_to)",
            "CREATE INDEX IF NOT EXISTS idx_payments_user        ON payments(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_payments_status      ON payments(status)",
            "CREATE INDEX IF NOT EXISTS idx_purchases_user       ON purchases(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_referrals_referrer   ON referrals(referrer_id)",
            "CREATE INDEX IF NOT EXISTS idx_users_status         ON users(status)",
            "CREATE INDEX IF NOT EXISTS idx_delivery_slots_payment ON delivery_slots(payment_id, status)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_panel_configs_payment_slot ON panel_configs(payment_id, delivery_slot_index) WHERE payment_id IS NOT NULL AND delivery_slot_index IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_delivery_queue_payment_slot_pending ON delivery_queue(payment_id, slot_index) WHERE payment_id IS NOT NULL AND slot_index IS NOT NULL AND status='pending'",

        ]
        for sql in indexes:
            try:
                conn.execute(sql)
            except Exception:
                pass
        # Initialize sort_order for existing rows that still have the default 0
        try:
            conn.execute(
                "UPDATE config_types SET sort_order=id WHERE sort_order=0"
            )
        except Exception:
            pass
        # ── Seed support_methods from legacy settings (if table is empty) ─────
        try:
            if conn.execute("SELECT COUNT(*) FROM support_methods").fetchone()[0] == 0:
                from datetime import datetime as _dt_seed
                _ts_seed = _dt_seed.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                _sort_seed = 0
                _tg_row = conn.execute(
                    "SELECT value FROM settings WHERE key='support_username'"
                ).fetchone()
                _lk_row = conn.execute(
                    "SELECT value FROM settings WHERE key='support_link'"
                ).fetchone()
                _tg_val = (_tg_row[0] if _tg_row else "").strip()
                _lk_val = (_lk_row[0] if _lk_row else "").strip()
                if _tg_val:
                    if not _tg_val.startswith("http"):
                        _tg_val = "https://t.me/" + _tg_val.lstrip("@")
                    _sort_seed += 1
                    conn.execute(
                        "INSERT INTO support_methods"
                        "(title, emoji, color, url, enabled, sort_order, created_at, updated_at)"
                        " VALUES(?, ?, ?, ?, 1, ?, ?, ?)",
                        ("پشتیبانی تلگرام", "", "default", _tg_val, _sort_seed, _ts_seed, _ts_seed),
                    )
                if _lk_val:
                    _sort_seed += 1
                    conn.execute(
                        "INSERT INTO support_methods"
                        "(title, emoji, color, url, enabled, sort_order, created_at, updated_at)"
                        " VALUES(?, ?, ?, ?, 1, ?, ?, ?)",
                        ("پشتیبانی آنلاین", "", "default", _lk_val, _sort_seed, _ts_seed, _ts_seed),
                    )
        except Exception:
            pass
        # ── Delivery reconcile cutoff/watermark (one-shot seed) ──────────────
        # Protects existing databases from the worker resurrecting old, already
        # delivered orders after deploy.  For fresh installs MAX(payments.id)
        # is NULL → 0, which is correct (every future payment id will be > 0).
        try:
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES('delivery_reconcile_enabled','1')"
            )
            _has_cutoff = conn.execute(
                "SELECT 1 FROM settings WHERE key='delivery_reconcile_after_payment_id'"
            ).fetchone()
            if not _has_cutoff:
                _max_pid_row = conn.execute(
                    "SELECT COALESCE(MAX(id), 0) AS m FROM payments"
                ).fetchone()
                _max_pid = int(_max_pid_row[0] if _max_pid_row else 0)
                conn.execute(
                    "INSERT INTO settings(key,value) VALUES('delivery_reconcile_after_payment_id', ?)",
                    (str(_max_pid),),
                )
        except Exception:
            pass
        conn.commit()
    finally:
        _init_conn.close()



# ── Settings ───────────────────────────────────────────────────────────────────
def setting_get(key, default=""):
    now = time.monotonic()
    with _SETTINGS_LOCK:
        fresh = (now - _SETTINGS_CACHE_TS) < _SETTINGS_CACHE_TTL
        if fresh:
            return _SETTINGS_CACHE.get(key, default)
    # Cache stale — reload from DB (outside lock to avoid blocking)
    try:
        _refresh_settings_cache(get_conn())
    except Exception:
        pass
    with _SETTINGS_LOCK:
        return _SETTINGS_CACHE.get(key, default)


def setting_set(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
    _invalidate_settings_cache()


# ── Bulk Sale ──────────────────────────────────────────────────────────────────
def get_bulk_qty_limits() -> tuple:
    """
    Return (min_qty: int, max_qty: int) for bulk purchases.
    max_qty == 0 means unlimited.
    """
    min_qty = max(1, int(setting_get("bulk_min_qty", "1") or "1"))
    max_qty = max(0, int(setting_get("bulk_max_qty", "0") or "0"))
    return min_qty, max_qty


def should_show_bulk_qty(user_id: int) -> bool:
    """
    Return True if the user should be shown the bulk quantity prompt.
    Modes:
    - 'everyone'    → all users
    - 'agents_only' → only users with is_agent=1
    - 'disabled'    → nobody (qty prompt hidden, behaves like qty=1)
    """
    mode = setting_get("bulk_sale_mode", "everyone")
    if mode == "disabled":
        return False
    if mode == "everyone":
        return True
    if mode == "agents_only":
        user = get_user(user_id)
        return bool(user and user["is_agent"])
    return False


# ── Users ──────────────────────────────────────────────────────────────────────
def ensure_user(tg_user):
    from .helpers import display_name
    uid       = tg_user.id
    full_name = display_name(tg_user)
    username  = tg_user.username or ""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET full_name=?, username=?, last_seen_at=? WHERE user_id=?",
                (full_name, username, now_str(), uid)
            )
            return False
        conn.execute(
            "INSERT INTO users(user_id,full_name,username,joined_at,last_seen_at,"
            "first_start_notified,status,is_agent) VALUES(?,?,?,?,?,0,'unsafe',0)",
            (uid, full_name, username, now_str(), now_str())
        )
        return True


def get_user(user_id):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()


def notify_first_start_if_needed(tg_user):
    from .config import ADMIN_IDS
    from .bot_instance import bot
    from .helpers import display_name, display_username, esc
    uid = tg_user.id
    with get_conn() as conn:
        row = conn.execute(
            "SELECT first_start_notified FROM users WHERE user_id=?", (uid,)
        ).fetchone()
        if not row or row["first_start_notified"]:
            return
        conn.execute(
            "UPDATE users SET first_start_notified=1 WHERE user_id=?", (uid,)
        )
    text = (
        "📢 | یه گل جدید عضو ربات شد:\n\n"
        f"نام: {display_name(tg_user)}\n"
        f"نام کاربری: {display_username(tg_user.username)}\n"
        f"آیدی عددی: <code>{tg_user.id}</code>"
    )
    if setting_get("notif_own_new_users", "1") == "1":
        for admin_id in ADMIN_IDS:
            try:
                bot.send_message(admin_id, text)
            except Exception:
                pass
    if setting_get("notif_bot_new_users", "1") == "1":
        import json as _json
        for row in get_all_admin_users():
            sub_id = row["user_id"]
            if sub_id in ADMIN_IDS:
                continue
            perms = _json.loads(row["permissions"] or "{}")
            if not (perms.get("full") or perms.get("approve_payments")):
                continue
            try:
                bot.send_message(sub_id, text)
            except Exception:
                pass
    from .group_manager import send_to_topic as _send_to_topic
    _send_to_topic("new_users", text)


def get_users(has_purchase=None, limit=None, offset=0, status=None, with_balance=False):
    q = (
        "SELECT u.*, "
        "(SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id)"
        "+ (SELECT COUNT(*) FROM panel_configs pc WHERE pc.user_id=u.user_id) AS purchase_count "
        "FROM users u WHERE 1=1"
    )
    params = []
    if has_purchase is True:
        q += (
            " AND (EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=u.user_id)"
            " OR EXISTS (SELECT 1 FROM panel_configs pc WHERE pc.user_id=u.user_id))"
        )
    elif has_purchase is False:
        q += (
            " AND NOT EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=u.user_id)"
            " AND NOT EXISTS (SELECT 1 FROM panel_configs pc WHERE pc.user_id=u.user_id)"
        )
    if status is not None:
        q += " AND u.status=?"
        params.append(status)
    if with_balance:
        q += " AND u.balance > 0"
        q += " ORDER BY u.balance DESC"
    else:
        q += " ORDER BY u.user_id DESC"
    if limit is not None:
        q += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    with get_conn() as conn:
        return conn.execute(q, params).fetchall()


def get_user_detail(user_id):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT u.*,
                   (SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id)
                   + (SELECT COUNT(*) FROM panel_configs pc WHERE pc.user_id=u.user_id) AS purchase_count,
                   (SELECT COALESCE(SUM(p.amount),0) FROM purchases p WHERE p.user_id=u.user_id)
                   + (SELECT COALESCE(SUM(py.amount),0) FROM payments py
                      INNER JOIN panel_configs pc ON pc.payment_id=py.id
                      WHERE pc.user_id=u.user_id AND py.status='completed' AND py.kind='config_purchase') AS total_spent,
                   (SELECT COUNT(*) FROM payments py WHERE py.user_id=u.user_id AND py.kind IN ('renewal','pnlcfg_renewal') AND py.status='completed') AS renewal_count,
                   (SELECT COALESCE(SUM(amount),0) FROM payments py WHERE py.user_id=u.user_id AND py.kind IN ('renewal','pnlcfg_renewal') AND py.status='completed') AS total_renewals,
                   (SELECT COALESCE(SUM(py2.amount),0) FROM payments py2 WHERE py2.user_id=u.user_id AND py2.status='completed' AND py2.payment_method != 'wallet') AS total_direct_payments,
                   (SELECT COUNT(*) FROM panel_configs pc WHERE pc.user_id=u.user_id) AS panel_sales_count,
                   (SELECT COUNT(*) FROM payments py WHERE py.user_id=u.user_id AND py.kind='pnlcfg_renewal' AND py.status='completed') AS panel_renew_count
            FROM users u WHERE u.user_id=?
            """,
            (user_id,)
        ).fetchone()


def count_all_users():
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]


def count_users_stats():
    """Return (total, with_purchase, new_today)."""
    from .helpers import now_str
    today = now_str()[:10]  # YYYY-MM-DD
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        buyers = conn.execute(
            """SELECT COUNT(DISTINCT uid) AS n FROM (
                SELECT user_id AS uid FROM purchases
                UNION
                SELECT user_id AS uid FROM panel_configs
            )"""
        ).fetchone()["n"]
        new_today = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE joined_at LIKE ?", (f"{today}%",)
        ).fetchone()["n"]
    return total, buyers, new_today


def search_users(query):
    query = query.lstrip("@").strip()
    with get_conn() as conn:
        base = (
            "SELECT u.*, "
            "(SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id)"
            "+ (SELECT COUNT(*) FROM panel_configs pc WHERE pc.user_id=u.user_id) AS purchase_count "
            "FROM users u WHERE "
        )
        if query.isdigit():
            return conn.execute(
                base + "u.user_id=? LIMIT 50", (int(query),)
            ).fetchall()
        return conn.execute(
            base + "(u.full_name LIKE ? OR u.username LIKE ?) "
            "ORDER BY u.user_id DESC LIMIT 50",
            (f"%{query}%", f"%{query}%")
        ).fetchall()


def update_balance(user_id, delta):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET balance=balance+? WHERE user_id=?", (delta, user_id)
        )


def update_admin_adjusted(user_id, delta):
    """Track admin manual balance additions/subtractions for statistics."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET total_admin_adjusted=total_admin_adjusted+? WHERE user_id=?",
            (delta, user_id)
        )


def set_balance(user_id, amount):
    with get_conn() as conn:
        conn.execute("UPDATE users SET balance=? WHERE user_id=?", (amount, user_id))


def set_phone_number(user_id: int, phone: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE users SET phone_number=? WHERE user_id=?", (phone, user_id))


def get_phone_number(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT phone_number FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row["phone_number"] if row else None


def set_user_status(user_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE users SET status=? WHERE user_id=?", (status, user_id))


def set_user_restricted(user_id, until_ts: int):
    """Restrict user. until_ts=0 means permanent; >0 means Unix timestamp when restriction expires."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET status='restricted', restricted_until=? WHERE user_id=?",
            (until_ts, user_id),
        )


def check_and_release_restriction(user_row) -> dict:
    """If user has a timed restriction that has expired, auto-release and return updated row."""
    import time as _time
    if not user_row:
        return user_row
    # sqlite3.Row lacks .get(); convert to dict for safe access
    if not isinstance(user_row, dict):
        user_row = dict(user_row)
    if user_row.get("status") == "restricted":
        until = user_row.get("restricted_until", 0)
        if until and until > 0 and _time.time() > until:
            set_user_status(user_row["user_id"], "unsafe")
            with get_conn() as conn:
                conn.execute(
                    "UPDATE users SET restricted_until=0 WHERE user_id=?",
                    (user_row["user_id"],),
                )
            user_row = dict(user_row)
            user_row["status"] = "unsafe"
            user_row["restricted_until"] = 0
    return user_row


def set_user_agent(user_id, is_agent):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET is_agent=? WHERE user_id=?", (is_agent, user_id)
        )


# ── Bulk user operations ───────────────────────────────────────────────────────
def _bulk_where(filter_type, user_ids):
    """Return (WHERE clause, params) for bulk queries."""
    if filter_type == "all":
        return "1=1", []
    if filter_type == "public":
        return "is_agent=0", []
    if filter_type == "agents":
        return "is_agent=1", []
    if filter_type == "buyers":
        return (
            "(EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=users.user_id)"
            " OR EXISTS (SELECT 1 FROM panel_configs pc WHERE pc.user_id=users.user_id))",
            []
        )
    if filter_type == "non_buyers":
        return (
            "(NOT EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=users.user_id)"
            " AND NOT EXISTS (SELECT 1 FROM panel_configs pc WHERE pc.user_id=users.user_id))",
            []
        )
    # specific list
    if not user_ids:
        return "0=1", []
    ph = ",".join("?" * len(user_ids))
    return f"user_id IN ({ph})", list(user_ids)


def bulk_add_balance(filter_type, user_ids, delta):
    where, params = _bulk_where(filter_type, user_ids)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET balance=balance+? WHERE {where}", [delta] + params)
        return conn.execute("SELECT changes()").fetchone()[0]


def bulk_zero_balance(filter_type, user_ids):
    where, params = _bulk_where(filter_type, user_ids)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET balance=0 WHERE {where}", params)
        return conn.execute("SELECT changes()").fetchone()[0]


def bulk_set_status(filter_type, user_ids, status):
    where, params = _bulk_where(filter_type, user_ids)
    with get_conn() as conn:
        conn.execute(f"UPDATE users SET status=? WHERE {where}", [status] + params)
        return conn.execute("SELECT changes()").fetchone()[0]


def count_users_by_filter(filter_type):
    """Count users for a given filter type."""
    with get_conn() as conn:
        if filter_type == "all":
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if filter_type == "public":
            return conn.execute("SELECT COUNT(*) FROM users WHERE is_agent=0").fetchone()[0]
        if filter_type == "agents":
            return conn.execute("SELECT COUNT(*) FROM users WHERE is_agent=1").fetchone()[0]
        if filter_type == "buyers":
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE"
                " (EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=users.user_id)"
                "  OR EXISTS (SELECT 1 FROM panel_configs pc WHERE pc.user_id=users.user_id))"
            ).fetchone()[0]
        if filter_type == "non_buyers":
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE"
                " (NOT EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=users.user_id)"
                "  AND NOT EXISTS (SELECT 1 FROM panel_configs pc WHERE pc.user_id=users.user_id))"
            ).fetchone()[0]
    return 0


# ── Config Types ───────────────────────────────────────────────────────────────
def get_all_types():
    with get_conn() as conn:
        try:
            return conn.execute(
                "SELECT * FROM config_types ORDER BY sort_order ASC, id ASC"
            ).fetchall()
        except Exception:
            return conn.execute(
                "SELECT * FROM config_types ORDER BY id ASC"
            ).fetchall()


def get_active_types():
    with get_conn() as conn:
        try:
            return conn.execute(
                "SELECT * FROM config_types WHERE is_active=1 ORDER BY sort_order ASC, id ASC"
            ).fetchall()
        except Exception:
            return conn.execute(
                "SELECT * FROM config_types WHERE is_active=1 ORDER BY id ASC"
            ).fetchall()


def get_type(type_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM config_types WHERE id=?", (type_id,)
        ).fetchone()


def add_type(name, description="", emoji="", button_color="glass", purchase_mode="step", invoice_description=""):
    with get_conn() as conn:
        try:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM config_types"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO config_types(name, description, emoji, button_color, sort_order, purchase_mode, invoice_description) VALUES(?, ?, ?, ?, ?, ?, ?)",
                (name.strip(), description.strip(), (emoji or "").strip(), button_color or "glass", max_order + 1, purchase_mode or "step", invoice_description or "")
            )
        except Exception:
            conn.execute(
                "INSERT INTO config_types(name, description, emoji, button_color) VALUES(?, ?, ?, ?)",
                (name.strip(), description.strip(), (emoji or "").strip(), button_color or "glass")
            )


def update_type_emoji(type_id, emoji):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET emoji=? WHERE id=?", ((emoji or "").strip(), type_id)
        )


def update_type_purchase_mode(type_id, mode):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET purchase_mode=? WHERE id=?", (mode or "step", type_id)
        )


def update_type_invoice_description(type_id, desc):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET invoice_description=? WHERE id=?", (desc or "", type_id)
        )


def update_type_glass_enabled_dims(type_id, dims_str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET glass_enabled_dims=? WHERE id=?", (dims_str or "v,d,u,q", type_id)
        )


def update_type_button_color(type_id, color):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET button_color=? WHERE id=?", (color or "glass", type_id)
        )


def update_type(type_id, new_name):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET name=? WHERE id=?", (new_name.strip(), type_id)
        )


def update_type_description(type_id, description):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET description=? WHERE id=?",
            (description.strip(), type_id)
        )


def update_type_active(type_id, is_active):
    with get_conn() as conn:
        conn.execute(
            "UPDATE config_types SET is_active=? WHERE id=?", (is_active, type_id)
        )


def reorder_type(type_id, new_position):
    """Move a type to new_position (1-indexed) and renumber all types."""
    with get_conn() as conn:
        try:
            all_types = conn.execute(
                "SELECT id FROM config_types ORDER BY sort_order ASC, id ASC"
            ).fetchall()
        except Exception:
            all_types = conn.execute(
                "SELECT id FROM config_types ORDER BY id ASC"
            ).fetchall()
        ids = [r["id"] for r in all_types]
        if type_id not in ids:
            return
        ids.remove(type_id)
        pos = max(1, min(new_position, len(ids) + 1)) - 1  # 0-indexed clamp
        ids.insert(pos, type_id)
        for order, tid in enumerate(ids, start=1):
            try:
                conn.execute(
                    "UPDATE config_types SET sort_order=? WHERE id=?", (order, tid)
                )
            except Exception:
                pass


def delete_type(type_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM config_types WHERE id=?", (type_id,))


# ── Support Methods ────────────────────────────────────────────────────────────────────────────────────
def get_support_methods(enabled_only=False):
    with get_conn() as conn:
        if enabled_only:
            return conn.execute(
                "SELECT * FROM support_methods WHERE enabled=1 ORDER BY sort_order ASC, id ASC"
            ).fetchall()
        return conn.execute(
            "SELECT * FROM support_methods ORDER BY sort_order ASC, id ASC"
        ).fetchall()


def get_support_method(method_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM support_methods WHERE id=?", (method_id,)
        ).fetchone()


def add_support_method(title, emoji, color, url):
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    with get_conn() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM support_methods"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO support_methods(title, emoji, color, url, enabled, sort_order, created_at, updated_at) "
            "VALUES(?, ?, ?, ?, 1, ?, ?, ?)",
            (title.strip(), (emoji or "").strip(), color or "default", url.strip(), max_order + 1, ts, ts)
        )


def update_support_method_field(method_id, field, value):
    _allowed = {"title", "emoji", "color", "url", "enabled", "sort_order"}
    if field not in _allowed:
        return
    ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    with get_conn() as conn:
        conn.execute(
            f"UPDATE support_methods SET {field}=?, updated_at=? WHERE id=?",
            (value, ts, method_id)
        )


def toggle_support_method(method_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT enabled FROM support_methods WHERE id=?", (method_id,)
        ).fetchone()
        if row:
            new_val = 0 if row["enabled"] else 1
            ts = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            conn.execute(
                "UPDATE support_methods SET enabled=?, updated_at=? WHERE id=?",
                (new_val, ts, method_id)
            )
            return new_val
    return None


def delete_support_method(method_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM support_methods WHERE id=?", (method_id,))


# ── Packages ───────────────────────────────────────────────────────────────────
def get_packages(type_id=None, price_only=None, include_inactive=False):
    q = """
        SELECT p.*, t.name AS type_name,
        (SELECT COUNT(*) FROM configs c WHERE c.package_id=p.id
         AND c.sold_to IS NULL AND c.reserved_payment_id IS NULL
         AND c.is_expired=0) AS stock
        FROM packages p
        JOIN config_types t ON t.id=p.type_id
        WHERE 1=1
    """
    if not include_inactive:
        q += " AND p.active=1"
    params = []
    if type_id is not None:
        q += " AND p.type_id=?"
        params.append(type_id)
    if price_only is not None:
        q += " AND p.price=?"
        params.append(price_only)
    q += " ORDER BY p.position ASC, p.id ASC"
    with get_conn() as conn:
        return conn.execute(q, params).fetchall()


def get_package(package_id):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT p.*, t.name AS type_name,
            (SELECT COUNT(*) FROM configs c WHERE c.package_id=p.id
             AND c.sold_to IS NULL AND c.reserved_payment_id IS NULL
             AND c.is_expired=0) AS stock
            FROM packages p
            JOIN config_types t ON t.id=p.type_id
            WHERE p.id=?
            """,
            (package_id,)
        ).fetchone()


def add_package(type_id, name, volume_gb, duration_days, price, show_name=1, max_users=0, buyer_role='all', button_color='glass', delivery_mode='config_only'):
    with get_conn() as conn:
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(position),0) FROM packages WHERE type_id=?", (type_id,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO packages(type_id,name,volume_gb,duration_days,price,active,position,show_name,max_users,buyer_role,button_color,delivery_mode)"
            " VALUES(?,?,?,?,?,1,?,?,?,?,?,?)",
            (type_id, name.strip(), volume_gb, duration_days, price, max_pos + 1, show_name, max_users, buyer_role, button_color or 'glass', delivery_mode or 'config_only')
        )
        return cur.lastrowid


def toggle_package_active(package_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE packages SET active=((active+1)%2) WHERE id=?", (package_id,)
        )


def update_package_field(package_id, field, value):
    allowed = {"name", "volume_gb", "duration_days", "price", "position", "show_name", "max_users", "buyer_role", "button_color"}
    if field not in allowed:
        return
    with get_conn() as conn:
        if field == "position":
            pkg = conn.execute(
                "SELECT type_id, position FROM packages WHERE id=?", (package_id,)
            ).fetchone()
            if pkg:
                old_pos = pkg["position"]
                new_pos = value
                type_id = pkg["type_id"]
                if new_pos != old_pos:
                    if new_pos < old_pos:
                        conn.execute(
                            "UPDATE packages SET position=position+1 "
                            "WHERE type_id=? AND position>=? AND position<? AND id!=?",
                            (type_id, new_pos, old_pos, package_id)
                        )
                    else:
                        conn.execute(
                            "UPDATE packages SET position=position-1 "
                            "WHERE type_id=? AND position>? AND position<=? AND id!=?",
                            (type_id, old_pos, new_pos, package_id)
                        )
                    conn.execute(
                        "UPDATE packages SET position=? WHERE id=?", (new_pos, package_id)
                    )
                    all_pkgs = conn.execute(
                        "SELECT id FROM packages WHERE type_id=? ORDER BY position ASC, id ASC",
                        (type_id,)
                    ).fetchall()
                    for idx, row in enumerate(all_pkgs, 1):
                        conn.execute(
                            "UPDATE packages SET position=? WHERE id=?", (idx, row["id"])
                        )
            return
        conn.execute(f"UPDATE packages SET {field}=? WHERE id=?", (value, package_id))


def delete_package(package_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM packages WHERE id=?", (package_id,))


# ── Configs / Stock ────────────────────────────────────────────────────────────
def count_available_manual_configs(package_id: int) -> int:
    """Count configs available for delivery (unsold, unreserved, not expired)."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM configs"
            " WHERE package_id=? AND sold_to IS NULL"
            " AND reserved_payment_id IS NULL AND is_expired=0",
            (package_id,),
        ).fetchone()["n"]


def add_config(type_id, package_id, service_name, config_text, inquiry_link):
    svc = service_name.strip()
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM configs WHERE package_id=? AND service_name=? LIMIT 1",
            (package_id, svc)
        ).fetchone()
        if existing:
            raise ValueError(f"کانفیگ با نام '{svc}' قبلاً در این پکیج ثبت شده است (id={existing['id']})")
        conn.execute(
            "INSERT INTO configs(type_id,package_id,service_name,config_text,"
            "inquiry_link,created_at) VALUES(?,?,?,?,?,?)",
            (type_id, package_id, svc,
             config_text.strip(), inquiry_link.strip(), now_str())
        )
    # Reset low-stock / empty-stock notification flags so they fire again
    # if stock later drops below threshold after being replenished.
    setting_set(f"stock_low_notif_{package_id}", "0")
    setting_set(f"stock_empty_notif_{package_id}", "0")


def get_registered_packages_stock():
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT p.id, p.name, p.volume_gb, p.duration_days, p.price,
                   t.name AS type_name,
                   COUNT(c.id) FILTER (WHERE c.sold_to IS NULL AND c.reserved_payment_id IS NULL
                                       AND c.is_expired=0)          AS stock,
                   COUNT(c.id) FILTER (WHERE c.sold_to IS NOT NULL) AS sold_count,
                   COUNT(c.id) FILTER (WHERE c.is_expired=1)        AS expired_count,
                   (SELECT COUNT(*) FROM pending_orders po
                    WHERE po.package_id=p.id AND po.status='waiting') AS pending_count
            FROM packages p
            JOIN config_types t ON t.id=p.type_id
            LEFT JOIN configs c ON c.package_id=p.id
            WHERE p.active=1
            GROUP BY p.id
            ORDER BY p.id DESC
            """
        ).fetchall()


def get_configs_paginated(package_id, sold, page=0):
    from .config import CONFIGS_PER_PAGE
    offset = page * CONFIGS_PER_PAGE
    if sold:
        q = ("SELECT * FROM configs WHERE package_id=? AND sold_to IS NOT NULL "
             "ORDER BY id DESC LIMIT ? OFFSET ?")
    else:
        q = ("SELECT * FROM configs WHERE package_id=? AND sold_to IS NULL "
             "AND reserved_payment_id IS NULL ORDER BY id ASC LIMIT ? OFFSET ?")
    with get_conn() as conn:
        return conn.execute(q, (package_id, CONFIGS_PER_PAGE, offset)).fetchall()


def count_configs(package_id, sold):
    if sold:
        q = "SELECT COUNT(*) AS n FROM configs WHERE package_id=? AND sold_to IS NOT NULL"
    else:
        q = ("SELECT COUNT(*) AS n FROM configs WHERE package_id=? "
             "AND sold_to IS NULL AND reserved_payment_id IS NULL")
    with get_conn() as conn:
        return conn.execute(q, (package_id,)).fetchone()["n"]


def get_available_configs_for_package(package_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM configs WHERE package_id=? AND sold_to IS NULL "
            "AND reserved_payment_id IS NULL AND is_expired=0 ORDER BY id ASC",
            (package_id,)
        ).fetchall()


def reserve_first_config(package_id, payment_id=None):
    with get_conn() as conn:
        # Always use atomic single-statement UPDATE to prevent race conditions.
        # When no payment_id is supplied (e.g. wallet / free-test), generate a
        # temporary unique key so the UPDATE still locks the row atomically.
        reserve_key = payment_id or f"tmp_{uuid.uuid4().hex}"
        conn.execute(
            "UPDATE configs SET reserved_payment_id=? "
            "WHERE id=("
            "  SELECT id FROM configs "
            "  WHERE package_id=? AND sold_to IS NULL "
            "  AND reserved_payment_id IS NULL AND is_expired=0 "
            "  ORDER BY id ASC LIMIT 1"
            ")",
            (reserve_key, package_id),
        )
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
        if changed == 0:
            return None
        row = conn.execute(
            "SELECT id FROM configs WHERE reserved_payment_id=? AND sold_to IS NULL",
            (reserve_key,),
        ).fetchone()
        return row["id"] if row else None


def release_reserved_config(config_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE configs SET reserved_payment_id=NULL WHERE id=?", (config_id,)
        )


def cleanup_stale_reservations():
    """Clear reserved_payment_id for configs that are stuck from a previous crash/restart.
    Safe to call at startup — never touches sold configs."""
    with get_conn() as conn:
        # 1. tmp_ reservations are always stale after a restart (used for wallet/free-test)
        c1 = conn.execute(
            "UPDATE configs SET reserved_payment_id=NULL "
            "WHERE sold_to IS NULL AND reserved_payment_id LIKE 'tmp_%'"
        )
        freed_tmp = conn.execute("SELECT changes() AS c").fetchone()["c"]

        # 2. Integer reservations where the payment is already rejected or error
        conn.execute(
            "UPDATE configs SET reserved_payment_id=NULL "
            "WHERE sold_to IS NULL "
            "  AND reserved_payment_id IS NOT NULL "
            "  AND reserved_payment_id NOT LIKE 'tmp_%' "
            "  AND CAST(reserved_payment_id AS INTEGER) IN ("
            "    SELECT id FROM payments WHERE status IN ('rejected','error')"
            "  )"
        )
        freed_bad = conn.execute("SELECT changes() AS c").fetchone()["c"]

    total = freed_tmp + freed_bad
    if total:
        import logging
        logging.getLogger(__name__).info(
            f"cleanup_stale_reservations: freed {total} stale config reservation(s) "
            f"(tmp={freed_tmp}, bad_payment={freed_bad})"
        )
    return total


def expire_config(config_id):
    with get_conn() as conn:
        conn.execute("UPDATE configs SET is_expired=1 WHERE id=?", (config_id,))


def update_config_field(config_id, field, value):
    """Update a single editable field on a config row."""
    allowed = {"service_name", "config_text", "inquiry_link", "package_id", "type_id"}
    if field not in allowed:
        raise ValueError(f"Field '{field}' is not editable")
    with get_conn() as conn:
        conn.execute(f"UPDATE configs SET {field}=? WHERE id=?", (value, config_id))


def assign_config_to_user(config_id, user_id, package_id, amount, payment_method, is_test=0):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO purchases(user_id,package_id,config_id,amount,"
            "payment_method,created_at,is_test) VALUES(?,?,?,?,?,?,?)",
            (user_id, package_id, config_id, amount, payment_method, now_str(), is_test)
        )
        purchase_id = conn.execute(
            "SELECT last_insert_rowid() AS x"
        ).fetchone()["x"]
        result = conn.execute(
            "UPDATE configs SET sold_to=?, purchase_id=?, sold_at=?, "
            "reserved_payment_id=NULL WHERE id=? AND sold_to IS NULL",
            (user_id, purchase_id, now_str(), config_id)
        )
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
        if changed == 0:
            # Config was already sold to someone else (concurrent approval)
            conn.execute("DELETE FROM purchases WHERE id=?", (purchase_id,))
            raise RuntimeError(
                f"Config {config_id} was already assigned to another user "
                "(concurrent payment approval detected)."
            )
        return purchase_id


def get_purchase(purchase_id):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT pr.*, p.name AS package_name, p.show_name, p.volume_gb, p.duration_days, p.price, p.max_users,
                   t.name AS type_name, t.description AS type_description,
                   c.service_name, c.config_text, c.inquiry_link,
                   CASE WHEN pr.is_test=1
                        AND (julianday('now') - julianday(pr.created_at)) * 24 >= p.duration_days * 24
                        THEN 1 ELSE c.is_expired END AS is_expired,
                   CASE WHEN pr.is_test=1
                        THEN MAX(0, p.duration_days * 24 - CAST((julianday('now') - julianday(pr.created_at)) * 24 AS INTEGER))
                        ELSE NULL END AS test_hours_left
            FROM purchases pr
            JOIN packages p ON p.id=pr.package_id
            JOIN config_types t ON t.id=p.type_id
            JOIN configs c ON c.id=pr.config_id
            WHERE pr.id=?
            """,
            (purchase_id,)
        ).fetchone()


def get_user_purchases(user_id):
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT pr.*, p.name AS package_name, p.show_name, p.volume_gb, p.duration_days, p.price,
                   t.name AS type_name, t.description AS type_description,
                   c.service_name, c.config_text, c.inquiry_link,
                   CASE WHEN pr.is_test=1
                        AND (julianday('now') - julianday(pr.created_at)) * 24 >= p.duration_days * 24
                        THEN 1 ELSE c.is_expired END AS is_expired,
                   CASE WHEN pr.is_test=1
                        THEN MAX(0, p.duration_days * 24 - CAST((julianday('now') - julianday(pr.created_at)) * 24 AS INTEGER))
                        ELSE NULL END AS test_hours_left
            FROM purchases pr
            JOIN packages p ON p.id=pr.package_id
            JOIN config_types t ON t.id=p.type_id
            JOIN configs c ON c.id=pr.config_id
            WHERE pr.user_id=?
            ORDER BY pr.id DESC
            """,
            (user_id,)
        ).fetchall()


def get_user_purchases_paged(user_id, page=0, per_page=10, search=None):
    """Return paginated purchases for a user with optional search."""
    with get_conn() as conn:
        base = """
            FROM purchases pr
            JOIN packages p ON p.id=pr.package_id
            JOIN config_types t ON t.id=p.type_id
            JOIN configs c ON c.id=pr.config_id
            WHERE pr.user_id=?
        """
        params = [user_id]
        if search:
            base += " AND (c.service_name LIKE ? OR c.config_text LIKE ? OR p.name LIKE ? OR t.name LIKE ?)"
            s = f"%{search}%"
            params += [s, s, s, s]
        count = conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = conn.execute(
            "SELECT pr.*, p.name AS package_name, p.show_name, p.volume_gb, p.duration_days, p.price,"
            "       t.name AS type_name, t.description AS type_description,"
            "       c.service_name, c.config_text, c.inquiry_link,"
            "       CASE WHEN pr.is_test=1"
            "            AND (julianday('now') - julianday(pr.created_at)) * 24 >= p.duration_days * 24"
            "            THEN 1 ELSE c.is_expired END AS is_expired,"
            "       CASE WHEN pr.is_test=1"
            "            THEN MAX(0, p.duration_days * 24 - CAST((julianday('now') - julianday(pr.created_at)) * 24 AS INTEGER))"
            "            ELSE NULL END AS test_hours_left "
            + base +
            " ORDER BY pr.id DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]
        ).fetchall()
        return rows, count


def get_user_panel_configs_paged(user_id, page=0, per_page=10, search=None):
    """Return paginated panel configs for a user with optional search."""
    with get_conn() as conn:
        base = """
            FROM panel_configs pc
            LEFT JOIN packages p ON pc.package_id = p.id
            LEFT JOIN config_types t ON t.id = p.type_id
            WHERE pc.user_id=?
        """
        params = [user_id]
        if search:
            base += " AND (pc.client_name LIKE ? OR pc.client_sub_url LIKE ? OR pc.client_config_text LIKE ?)"
            s = f"%{search}%"
            params += [s, s, s]
        count = conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = conn.execute(
            "SELECT pc.*, p.name AS package_name, p.volume_gb, p.duration_days,"
            "       t.name AS type_name "
            + base +
            " ORDER BY pc.id DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]
        ).fetchall()
        return rows, count


def get_user_config_package_groups(user_id):
    """Return (manual_groups, panel_groups) for grouping a user's configs by package.
    Each group has keys: pkg_id, pkg_name, cnt.
    """
    with get_conn() as conn:
        manual_groups = conn.execute(
            """
            SELECT p.id AS pkg_id, p.name AS pkg_name, COUNT(*) AS cnt
            FROM purchases pr
            JOIN packages p ON p.id = pr.package_id
            WHERE pr.user_id = ?
            GROUP BY p.id, p.name
            ORDER BY p.name
            """,
            (user_id,)
        ).fetchall()
        panel_groups = conn.execute(
            """
            SELECT COALESCE(p.id, 0) AS pkg_id,
                   COALESCE(p.name, '(بدون پکیج)') AS pkg_name,
                   COUNT(*) AS cnt
            FROM panel_configs pc
            LEFT JOIN packages p ON p.id = pc.package_id
            WHERE pc.user_id = ?
            GROUP BY p.id, p.name
            ORDER BY p.name
            """,
            (user_id,)
        ).fetchall()
    return list(manual_groups), list(panel_groups)


def get_user_purchases_for_package(user_id, package_id, page=0, per_page=10):
    """Return paginated purchases for a specific package."""
    with get_conn() as conn:
        base = (
            "FROM purchases pr "
            "JOIN packages p ON p.id=pr.package_id "
            "JOIN config_types t ON t.id=p.type_id "
            "JOIN configs c ON c.id=pr.config_id "
            "WHERE pr.user_id=? AND pr.package_id=?"
        )
        count = conn.execute("SELECT COUNT(*) AS n " + base, (user_id, package_id)).fetchone()["n"]
        rows = conn.execute(
            "SELECT pr.*, p.name AS package_name, p.show_name, p.volume_gb, p.duration_days, p.price,"
            "       t.name AS type_name, t.description AS type_description,"
            "       c.service_name, c.config_text, c.inquiry_link,"
            "       CASE WHEN pr.is_test=1"
            "            AND (julianday('now') - julianday(pr.created_at)) * 24 >= p.duration_days * 24"
            "            THEN 1 ELSE c.is_expired END AS is_expired,"
            "       CASE WHEN pr.is_test=1"
            "            THEN MAX(0, p.duration_days * 24 - CAST((julianday('now') - julianday(pr.created_at)) * 24 AS INTEGER))"
            "            ELSE NULL END AS test_hours_left "
            + base
            + " ORDER BY pr.id DESC LIMIT ? OFFSET ?",
            (user_id, package_id, per_page, page * per_page)
        ).fetchall()
        return rows, count


def get_user_panel_configs_for_package(user_id, package_id, page=0, per_page=10):
    """Return paginated panel configs for a specific package (0 = no package)."""
    with get_conn() as conn:
        if package_id == 0:
            base = (
                "FROM panel_configs pc "
                "LEFT JOIN packages p ON pc.package_id = p.id "
                "LEFT JOIN config_types t ON t.id = p.type_id "
                "WHERE pc.user_id=? AND pc.package_id IS NULL"
            )
            params = [user_id]
        else:
            base = (
                "FROM panel_configs pc "
                "LEFT JOIN packages p ON pc.package_id = p.id "
                "LEFT JOIN config_types t ON t.id = p.type_id "
                "WHERE pc.user_id=? AND pc.package_id=?"
            )
            params = [user_id, package_id]
        count = conn.execute("SELECT COUNT(*) AS n " + base, params).fetchone()["n"]
        rows = conn.execute(
            "SELECT pc.*, p.name AS package_name, p.volume_gb, p.duration_days,"
            "       t.name AS type_name "
            + base
            + " ORDER BY pc.id DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]
        ).fetchall()
        return rows, count


def user_has_test_for_type(user_id, type_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM purchases pr "
            "JOIN packages p ON p.id=pr.package_id "
            "WHERE pr.user_id=? AND p.type_id=? AND pr.is_test=1",
            (user_id, type_id)
        ).fetchone()
    return row["n"] > 0


def user_has_any_test(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM purchases WHERE user_id=? AND is_test=1",
            (user_id,)
        ).fetchone()
        if row["n"] > 0:
            return True
        row2 = conn.execute(
            "SELECT COUNT(*) AS n FROM panel_configs WHERE user_id=? AND is_test=1",
            (user_id,)
        ).fetchone()
        return row2["n"] > 0


def reset_all_free_tests():
    with get_conn() as conn:
        conn.execute("DELETE FROM purchases WHERE is_test=1")
        conn.execute("UPDATE panel_configs SET is_test=0 WHERE is_test=1")


def agent_test_count_in_period(user_id, period):
    import jdatetime as _jdt
    from .helpers import _TZ_TEHRAN
    now_j = _jdt.datetime.fromgregorian(datetime=__import__("datetime").datetime.now(_TZ_TEHRAN))
    zero = now_j.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        start_j = zero
    elif period == "week":
        # Iranian week starts on Saturday; jdatetime weekday(): 0=Saturday
        start_j = zero - __import__("datetime").timedelta(days=now_j.weekday())
    elif period == "month":
        start_j = zero.replace(day=1)
    else:
        start_j = zero
    start = start_j.strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM purchases WHERE user_id=? AND is_test=1 AND created_at>=?",
            (user_id, start)
        ).fetchone()
        cnt = row["cnt"] if row else 0
        row2 = conn.execute(
            "SELECT COUNT(*) as cnt FROM panel_configs WHERE user_id=? AND is_test=1 AND created_at>=?",
            (user_id, start)
        ).fetchone()
        cnt += row2["cnt"] if row2 else 0
    return cnt


# ── Agency Prices ──────────────────────────────────────────────────────────────
def get_agency_price(user_id, package_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT price FROM agency_prices WHERE user_id=? AND package_id=?",
            (user_id, package_id)
        ).fetchone()
    return row["price"] if row else None


def set_agency_price(user_id, package_id, price):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agency_prices(user_id,package_id,price) VALUES(?,?,?) "
            "ON CONFLICT(user_id,package_id) DO UPDATE SET price=excluded.price",
            (user_id, package_id, price)
        )


def get_agency_price_config(user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agency_price_config WHERE user_id=?", (user_id,)
        ).fetchone()
    if row:
        return dict(row)
    return {"price_mode": "package", "global_type": "pct", "global_val": 0}


def set_agency_price_config(user_id, price_mode, global_type="pct", global_val=0):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agency_price_config(user_id,price_mode,global_type,global_val) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET price_mode=excluded.price_mode,"
            "global_type=excluded.global_type,global_val=excluded.global_val",
            (user_id, price_mode, global_type, global_val)
        )


def get_agency_type_discount(user_id, type_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM agency_type_discount WHERE user_id=? AND type_id=?",
            (user_id, type_id)
        ).fetchone()
    return dict(row) if row else None


def set_agency_type_discount(user_id, type_id, discount_type, discount_value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agency_type_discount(user_id,type_id,discount_type,discount_value) VALUES(?,?,?,?) "
            "ON CONFLICT(user_id,type_id) DO UPDATE SET discount_type=excluded.discount_type,"
            "discount_value=excluded.discount_value",
            (user_id, type_id, discount_type, discount_value)
        )


def get_agencies():
    """Return all users with is_agent=1."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE is_agent=1 ORDER BY user_id DESC"
        ).fetchall()


# ── Payments ───────────────────────────────────────────────────────────────────
def get_invoice_expire_minutes() -> int:
    """Configured invoice lifetime in minutes."""
    try:
        return max(1, int(setting_get("invoice_expiry_minutes", "30") or "30"))
    except Exception:
        return 30


def is_invoice_expiry_enabled() -> bool:
    return setting_get("invoice_expiry_enabled", "1") == "1"


def _jalali_datetime_str(dt: datetime) -> str:
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y-%m-%d %H:%M:%S")


def _calculate_invoice_expires_at():
    if not is_invoice_expiry_enabled():
        return None
    expires_dt = datetime.now(_TZ_TEHRAN) + timedelta(minutes=get_invoice_expire_minutes())
    return _jalali_datetime_str(expires_dt)


def _row_value(row, key, default=None):
    try:
        if hasattr(row, "keys") and key not in row.keys():
            return default
        value = row[key]
        return default if value is None else value
    except Exception:
        try:
            return row.get(key, default)
        except Exception:
            return default


def _parse_payment_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            if int(text[:4]) < 1700:
                return jdatetime.datetime.strptime(text, fmt).togregorian().replace(tzinfo=_TZ_TEHRAN)
        except Exception:
            pass
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=_TZ_TEHRAN)
        except Exception:
            pass
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_TZ_TEHRAN)
        return parsed.astimezone(_TZ_TEHRAN)
    except Exception:
        return None


def get_payment_expires_at(payment):
    """Return the immutable invoice expiration timestamp stored on the payment."""
    return _row_value(payment, "expires_at") if payment else None


def is_payment_expired(payment) -> bool:
    """True when expiry is enabled and this payment's stored expires_at is in the past."""
    if not payment or not is_invoice_expiry_enabled():
        return False
    expires_dt = _parse_payment_datetime(get_payment_expires_at(payment))
    if not expires_dt:
        return False
    return datetime.now(_TZ_TEHRAN) >= expires_dt


def format_payment_expire_text(payment) -> str:
    """Persian UI line for an existing payment invoice expiration."""
    if not payment or not is_invoice_expiry_enabled():
        return ""
    expires_at = get_payment_expires_at(payment)
    if not expires_at:
        return ""
    if is_payment_expired(payment):
        return "⏳ زمان پرداخت شما به پایان رسید\nلطفاً مجدداً خرید خود را انجام دهید"
    return f"⏰ مهلت پرداخت تا: {expires_at}"


def create_payment(kind, user_id, package_id, amount, payment_method,
                   status="pending", config_id=None, crypto_coin=None, final_amount=None, quantity=1):
    expires_at = _calculate_invoice_expires_at()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO payments(kind,user_id,package_id,amount,payment_method,"
            "status,created_at,expires_at,config_id,crypto_coin,final_amount,quantity) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, user_id, package_id, amount, payment_method,
             status, now_str(), expires_at, config_id, crypto_coin, final_amount, max(1, int(quantity or 1)))
        )
        return conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]


def update_payment_final_amount(payment_id, final_amount):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET final_amount=? WHERE id=?",
            (final_amount, payment_id)
        )


def set_payment_service_names(payment_id, names: list):
    """Persist the ordered list of chosen service names for a panel config payment."""
    import json as _json
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET service_names_json=? WHERE id=?",
            (_json.dumps(names, ensure_ascii=False), payment_id)
        )


def get_payment_service_names(payment_id) -> list:
    """Return the saved service names list for a payment, or None if not set."""
    import json as _json
    with get_conn() as conn:
        row = conn.execute(
            "SELECT service_names_json FROM payments WHERE id=?", (payment_id,)
        ).fetchone()
    if not row or not row["service_names_json"]:
        return None
    try:
        result = _json.loads(row["service_names_json"])
        return result if isinstance(result, list) and result else None
    except Exception:
        return None


def update_payment_crypto_comment(payment_id, comment_code):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET crypto_comment=? WHERE id=?",
            (comment_code, payment_id)
        )


def update_payment_crypto_amount(payment_id, coin_amount_str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET crypto_amount=? WHERE id=?",
            (coin_amount_str, payment_id)
        )


def get_payment(payment_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE id=?", (payment_id,)
        ).fetchone()


def get_payment_by_gateway_ref(gateway_ref: str, payment_method: str = "centralpay"):
    """Find a payment by the gateway-side reference/order id."""
    ref = str(gateway_ref or "").strip()
    if not ref:
        return None
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE gateway_ref=? AND payment_method=? ORDER BY id DESC LIMIT 1",
            (ref, payment_method),
        ).fetchone()


def get_gateway_stats(payment_method: str) -> dict:
    """
    Return completed payment stats for a given payment_method.

    Returns:
        {
            "total_toman": <int>,        # sum of amount column (toman)
            "count": <int>,              # number of completed payments
            "by_coin": {                 # populated only when crypto_coin rows exist
                "<coin>": {
                    "toman": <int>,
                    "crypto": <float or None>,  # sum of crypto_amount if available
                }
            }
        }
    """
    with get_conn() as conn:
        # Overall totals
        row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount),0) AS total"
            " FROM payments"
            " WHERE payment_method=? AND status='completed'",
            (payment_method,),
        ).fetchone()
        total_toman = int(row["total"]) if row else 0
        count = int(row["cnt"]) if row else 0

        # Per-coin breakdown
        coin_rows = conn.execute(
            "SELECT crypto_coin,"
            " COUNT(*) AS cnt,"
            " COALESCE(SUM(amount), 0) AS toman_sum,"
            " COALESCE(SUM(CAST(REPLACE(crypto_amount,'',crypto_amount) AS REAL)), 0) AS crypto_sum"
            " FROM payments"
            " WHERE payment_method=? AND status='completed' AND crypto_coin IS NOT NULL AND crypto_coin != ''"
            " GROUP BY crypto_coin",
            (payment_method,),
        ).fetchall()

    by_coin = {}
    for cr in coin_rows:
        coin = cr["crypto_coin"]
        crypto_val = None
        try:
            v = float(cr["crypto_sum"])
            if v > 0:
                crypto_val = v
        except Exception:
            pass
        by_coin[coin] = {
            "toman": int(cr["toman_sum"]),
            "count": int(cr["cnt"]),
            "crypto": crypto_val,
        }

    return {"total_toman": total_toman, "count": count, "by_coin": by_coin}


def get_card_payment_stats() -> list:
    """
    Return per-card payment stats for completed card payments.

    Each item:
        {
            "card_id": <int or None>,
            "card_number": <str>,
            "bank_name": <str>,
            "holder_name": <str>,
            "is_active": <int>,
            "total_toman": <int>,
            "count": <int>,
        }
    Cards with no payments are also included (total=0, count=0).
    Plus an extra entry for payments with no card_id (legacy).
    """
    with get_conn() as conn:
        # Per-card aggregates
        rows = conn.execute(
            "SELECT p.used_card_id,"
            " COALESCE(SUM(p.amount), 0) AS total,"
            " COUNT(*) AS cnt"
            " FROM payments p"
            " WHERE p.payment_method='card' AND p.status='completed'"
            " GROUP BY p.used_card_id"
        ).fetchall()

        cards = conn.execute(
            "SELECT id, card_number, bank_name, holder_name, is_active"
            " FROM payment_cards ORDER BY id ASC"
        ).fetchall()

    stats_map = {}
    for r in rows:
        cid = r["used_card_id"]
        stats_map[cid] = {"total_toman": int(r["total"]), "count": int(r["cnt"])}

    result = []
    known_ids = set()
    for c in cards:
        cid = c["id"]
        known_ids.add(cid)
        s = stats_map.get(cid, {"total_toman": 0, "count": 0})
        result.append({
            "card_id": cid,
            "card_number": c["card_number"],
            "bank_name": c["bank_name"] or "",
            "holder_name": c["holder_name"] or "",
            "is_active": c["is_active"],
            "total_toman": s["total_toman"],
            "count": s["count"],
        })

    # Legacy / unlinked payments (NULL card_id or id not in payment_cards)
    unlinked_total = 0
    unlinked_count = 0
    for cid, s in stats_map.items():
        if cid not in known_ids:
            unlinked_total += s["total_toman"]
            unlinked_count += s["count"]
    if unlinked_count > 0:
        result.append({
            "card_id": None,
            "card_number": "—",
            "bank_name": "پرداخت‌های قدیمی",
            "holder_name": "",
            "is_active": 1,
            "total_toman": unlinked_total,
            "count": unlinked_count,
        })

    return result


def get_pending_crypto_payments(limit=30):
    """Return pending payments for automated crypto gateways (plisio/nowpayments)
    that have a receipt_text (invoice/txn ID) and are still pending."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.*, u.full_name, u.username"
            " FROM payments p"
            " LEFT JOIN users u ON u.user_id = p.user_id"
            " WHERE p.status = 'pending'"
            " AND p.payment_method IN ('plisio', 'nowpayments')"
            " AND p.receipt_text IS NOT NULL AND p.receipt_text != ''"
            " ORDER BY p.created_at DESC"
            " LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_pending_payments_page(page=0, page_size=10):
    """Return (total_count, list_of_dicts) for pending payments with submitted receipts.

    Only card/crypto payments where the user has actually submitted a receipt
    (receipt_file_id IS NOT NULL or receipt_text is non-empty) are included.
    - Automated gateways (tetrapay, tronpays_rial, swapwallet_crypto) are excluded
      because they pre-set receipt_text to an auth/invoice ID and self-verify.
    - Payments that only reached 'pending' by opening the card/wallet copy page
      without submitting a receipt are also excluded.
    """
    _PENDING_FILTER = (
        " AND p.payment_method IN ('card', 'crypto')"
        " AND (p.receipt_file_id IS NOT NULL"
        " OR (p.receipt_text IS NOT NULL AND p.receipt_text != ''))"
    )
    offset = page * page_size
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM payments p"
            " WHERE p.status='pending'" + _PENDING_FILTER
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT p.*, u.full_name, u.username,"
            " pk.name AS pkg_name, t.name AS type_name, pk.volume_gb, pk.duration_days"
            " FROM payments p"
            " LEFT JOIN users u ON u.user_id = p.user_id"
            " LEFT JOIN packages pk ON pk.id = p.package_id"
            " LEFT JOIN config_types t ON t.id = pk.type_id"
            " WHERE p.status = 'pending'" + _PENDING_FILTER +
            " ORDER BY p.created_at ASC"
            " LIMIT ? OFFSET ?",
            (page_size, offset)
        ).fetchall()
    return total, [dict(r) for r in rows]


def update_payment_receipt(payment_id, file_id, text_value):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET receipt_file_id=?, receipt_text=? WHERE id=?",
            (file_id, text_value, payment_id)
        )


def approve_payment(payment_id, admin_note):
    """Mark payment approved by admin. No expiry check — admin decision is final."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET status='approved', admin_note=?, approved_at=? WHERE id=? AND status='pending'",
            (admin_note, now_str(), payment_id)
        )


def reject_payment(payment_id, admin_note):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET status='rejected', admin_note=?, approved_at=? WHERE id=? AND status='pending'",
            (admin_note, now_str(), payment_id)
        )


def complete_payment(payment_id, force=False):
    """Mark payment completed. Returns True if this call won the race, False if already processed.
    force=True skips the expiry check (used for admin manual approval)."""
    with get_conn() as conn:
        payment = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not force and is_payment_expired(payment):
            print(f"[EXPIRED PAYMENT IGNORED] payment_id={payment_id}")
            return False
        conn.execute(
            "UPDATE payments SET status='completed', approved_at=?, fulfilled_at=? WHERE id=? AND status IN ('pending', 'approved', 'processing')",
            (now_str(), now_str(), payment_id)
        )
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
        won = changed > 0
    if won:
        try:
            import threading as _thr
            from .group_manager import log_gateway_payment as _lgp
            _thr.Thread(target=_lgp, args=(payment_id,), daemon=True).start()
        except Exception:
            pass
    return won


def lock_tronado_payment(payment_id: int) -> bool:
    """
    Atomically move a pending tronado payment to 'processing'.
    Returns True if this call won the race (was pending before this call).
    Returns False if already processing, completed, or any other non-pending status.
    Must be called inside a BEGIN IMMEDIATE transaction for true isolation.
    """
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE payments SET status='processing' WHERE id=? AND payment_method='tronado' AND status='pending'",
            (payment_id,)
        )
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.execute("COMMIT")
        return changed > 0


def save_tronado_callback_data(payment_id: int, raw_payload: str,
                                gateway_ref: str = "", external_txid: str = ""):
    """Persist raw IPN payload and reference IDs for audit."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET raw_callback=?, callback_received_at=?,"
            " gateway_ref=COALESCE(NULLIF(?, ''), gateway_ref),"
            " external_txid=COALESCE(NULLIF(?, ''), external_txid)"
            " WHERE id=?",
            (raw_payload[:4000] if raw_payload else None,
             now_str(),
             gateway_ref or "",
             external_txid or "",
             payment_id)
        )


def lock_centralpay_payment(payment_id: int) -> bool:
    """
    Atomically move a pending centralpay payment to 'processing'.
    Returns True if this call won the race (was pending before this call).
    Returns False if already processing, completed, or any other non-pending status.
    """
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE payments SET status='processing' WHERE id=? AND payment_method='centralpay' AND status='pending'",
            (payment_id,)
        )
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.execute("COMMIT")
        return changed > 0


# ── Admin Users ────────────────────────────────────────────────────────────────
def get_admin_user(user_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM admin_users WHERE user_id=?", (user_id,)
        ).fetchone()


def get_all_admin_users():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM admin_users ORDER BY added_at DESC"
        ).fetchall()


def add_admin_user(user_id, added_by, permissions_dict):
    perms_json = json.dumps(permissions_dict, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO admin_users(user_id,added_by,added_at,permissions) VALUES(?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET permissions=excluded.permissions,"
            " added_by=excluded.added_by, added_at=excluded.added_at",
            (user_id, added_by, now_str(), perms_json)
        )


def remove_admin_user(user_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM admin_users WHERE user_id=?", (user_id,))


def update_admin_permissions(user_id, permissions_dict):
    perms_json = json.dumps(permissions_dict, ensure_ascii=False)
    with get_conn() as conn:
        conn.execute(
            "UPDATE admin_users SET permissions=? WHERE user_id=?",
            (perms_json, user_id)
        )


# ── Pending Orders ─────────────────────────────────────────────────────────────
def create_pending_order(user_id, package_id, payment_id, amount, payment_method, quantity=1):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pending_orders(user_id,package_id,payment_id,amount,"
            "payment_method,created_at,status,quantity) VALUES(?,?,?,?,?,?,?,?)",
            (user_id, package_id, payment_id, amount,
             payment_method, now_str(), "waiting", max(1, int(quantity or 1)))
        )
        return conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]


def get_pending_order(pending_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_orders WHERE id=?", (pending_id,)
        ).fetchone()


# ── Discount Codes ─────────────────────────────────────────────────────────────
def get_all_discount_codes():
    with get_conn() as conn:
        return conn.execute(
            "SELECT dc.*, "
            "(SELECT COUNT(*) FROM discount_code_uses WHERE code_id=dc.id) as actual_uses "
            "FROM discount_codes dc ORDER BY dc.id DESC"
        ).fetchall()


def get_discount_code(code_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT dc.*, "
            "(SELECT COUNT(*) FROM discount_code_uses WHERE code_id=dc.id) as actual_uses "
            "FROM discount_codes dc WHERE dc.id=?",
            (code_id,)
        ).fetchone()


def get_discount_code_by_code(code):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM discount_codes WHERE LOWER(code)=LOWER(?)",
            (code.strip(),)
        ).fetchone()


def add_discount_code(code, discount_type, discount_value, max_uses_total, max_uses_per_user, audience="all", scope_type="all", usage_scope="all"):
    audience = audience if audience in ("all", "public", "agents") else "all"
    scope_type = scope_type if scope_type in ("all", "types", "packages") else "all"
    usage_scope = usage_scope if usage_scope in ("all", "package", "addon_volume", "addon_time") else "all"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO discount_codes(code, discount_type, discount_value, "
            "max_uses_total, max_uses_per_user, used_count, is_active, created_at, audience, scope_type, usage_scope) "
            "VALUES(?,?,?,?,?,0,1,?,?,?,?)",
            (code.strip().upper(), discount_type, int(discount_value),
             int(max_uses_total), int(max_uses_per_user), now_str(), audience, scope_type, usage_scope)
        )
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


def toggle_discount_code(code_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE discount_codes SET is_active = 1 - is_active WHERE id=?",
            (code_id,)
        )


def update_discount_code_field(code_id, field, value):
    _allowed = {"code", "discount_type", "discount_value", "max_uses_total", "max_uses_per_user", "audience", "scope_type"}
    if field not in _allowed:
        return
    with get_conn() as conn:
        conn.execute(
            f"UPDATE discount_codes SET {field}=? WHERE id=?",
            (value, code_id)
        )


def delete_discount_code(code_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM discount_codes WHERE id=?", (code_id,))


def get_discount_code_user_uses(code_id, user_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM discount_code_uses WHERE code_id=? AND user_id=?",
            (code_id, user_id)
        ).fetchone()
        return row["cnt"] if row else 0


def validate_discount_code(code, user_id, amount, is_agent=False, package_id=None, usage_scope="all"):
    """Returns (ok, row, discount_amount, final_amount, error_msg).
    usage_scope: 'all' | 'package' | 'addon_volume' | 'addon_time'
    """
    row = get_discount_code_by_code(code)
    if not row:
        return False, None, 0, amount, "❌ کد تخفیف وارد شده معتبر نیست."
    if not row["is_active"]:
        return False, None, 0, amount, "❌ این کد تخفیف غیرفعال است."
    if row["max_uses_total"] > 0 and row["used_count"] >= row["max_uses_total"]:
        return False, None, 0, amount, "❌ ظرفیت این کد تخفیف به پایان رسیده است."
    # Audience check
    audience = row["audience"] if "audience" in row.keys() else "all"
    if audience == "agents" and not is_agent:
        return False, None, 0, amount, "❌ این کد تخفیف فقط برای نمایندگان قابل استفاده است."
    if audience == "public" and is_agent:
        return False, None, 0, amount, "❌ این کد تخفیف فقط برای کاربران عادی قابل استفاده است."
    if row["max_uses_per_user"] > 0:
        user_uses = get_discount_code_user_uses(row["id"], user_id)
        if user_uses >= row["max_uses_per_user"]:
            return False, None, 0, amount, "❌ شما قبلاً از این کد تخفیف استفاده کرده‌اید."
    # Usage scope check (what type of purchase this code can be used for)
    row_usage_scope = row["usage_scope"] if "usage_scope" in row.keys() else "all"
    if row_usage_scope != "all" and usage_scope != "all":
        if row_usage_scope != usage_scope:
            return False, None, 0, amount, "❌ این کد تخفیف برای این نوع خرید قابل استفاده نیست."
    # Scope check (which category/package)
    scope_type = row["scope_type"] if "scope_type" in row.keys() else "all"
    if scope_type != "all" and package_id is not None:
        targets = get_discount_code_targets(row["id"])
        target_ids = {t["target_id"] for t in targets}
        if scope_type == "types":
            pkg = get_package(package_id)
            pkg_type_id = pkg["type_id"] if pkg else None
            if pkg_type_id not in target_ids:
                return False, None, 0, amount, "❌ این کد تخفیف برای این نوع سرویس قابل استفاده نیست."
        elif scope_type == "packages":
            if package_id not in target_ids:
                return False, None, 0, amount, "❌ این کد تخفیف برای این پکیج قابل استفاده نیست."
    if row["discount_type"] == "pct":
        disc = round(amount * row["discount_value"] / 100)
    else:
        disc = int(row["discount_value"])
    disc = min(disc, amount)
    final = max(0, amount - disc)
    return True, row, disc, final, None


def record_discount_usage(code_id, user_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO discount_code_uses(code_id, user_id, used_at) VALUES(?,?,?)",
            (code_id, user_id, now_str())
        )
        conn.execute(
            "UPDATE discount_codes SET used_count = used_count + 1 WHERE id=?",
            (code_id,)
        )


def has_eligible_discount_codes(is_agent: bool) -> bool:
    """Return True if there is at least one active discount code eligible for this user type."""
    with get_conn() as conn:
        if is_agent:
            row = conn.execute(
                "SELECT 1 FROM discount_codes "
                "WHERE is_active=1 AND (audience='all' OR audience='agents') LIMIT 1"
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM discount_codes "
                "WHERE is_active=1 AND (audience='all' OR audience='public') LIMIT 1"
            ).fetchone()
        return row is not None


def get_discount_code_targets(code_id):
    """Return list of target rows for a discount code."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM discount_code_targets WHERE code_id=? ORDER BY id ASC",
            (code_id,)
        ).fetchall()


def set_discount_code_targets(code_id, target_type, target_ids):
    """Replace all targets of the given target_type for a discount code."""
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM discount_code_targets WHERE code_id=? AND target_type=?",
            (code_id, target_type)
        )
        for tid in target_ids:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO discount_code_targets(code_id, target_type, target_id) VALUES(?,?,?)",
                    (code_id, target_type, int(tid))
                )
            except Exception:
                pass


def reject_all_pending_payments():
    """Reject all pending card/crypto payments that have a submitted receipt.

    Automated gateways (tetrapay, tronpays_rial, swapwallet_crypto) are excluded
    because they self-verify and should not be bulk-rejected.
    Payments without a submitted receipt (user only opened the card page) are
    also excluded to avoid wrongly rejecting in-progress sessions.
    Returns count of rejected payments.
    """
    _REJECT_FILTER = (
        " AND payment_method IN ('card', 'crypto')"
        " AND (receipt_file_id IS NOT NULL"
        " OR (receipt_text IS NOT NULL AND receipt_text != ''))"
    )
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM payments WHERE status='pending'" + _REJECT_FILTER
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.execute(
                "UPDATE payments SET status='rejected', admin_note=?, approved_at=? "
                "WHERE status='pending'" + _REJECT_FILTER,
                ("رد شد توسط ادمین (رد همه)", now_str())
            )
        return len(ids)


def fulfill_pending_order(pending_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_orders SET status='fulfilled' WHERE id=?", (pending_id,)
        )


def get_waiting_pending_orders_for_package(package_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_orders WHERE package_id=? AND status='waiting' "
            "ORDER BY created_at ASC",
            (package_id,)
        ).fetchall()


#  Pinned Messages 
def get_all_pinned_messages():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pinned_messages ORDER BY id ASC"
        ).fetchall()


def get_pinned_message(pin_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pinned_messages WHERE id=?", (pin_id,)
        ).fetchone()


def add_pinned_message(text):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pinned_messages(text, created_at) VALUES(?, ?)",
            (text, now_str())
        )
        return conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]


def update_pinned_message(pin_id, text):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pinned_messages SET text=? WHERE id=?",
            (text, pin_id)
        )


def delete_pinned_message(pin_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM pinned_messages WHERE id=?", (pin_id,))


def save_pinned_send(pin_id, user_id, message_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pinned_message_sends(pin_id, user_id, message_id) VALUES(?,?,?)",
            (pin_id, user_id, message_id)
        )


def get_pinned_sends(pin_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pinned_message_sends WHERE pin_id=?", (pin_id,)
        ).fetchall()


def delete_pinned_sends(pin_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM pinned_message_sends WHERE pin_id=?", (pin_id,))


# ── Referrals ──────────────────────────────────────────────────────────────────
def add_referral(referrer_id, referee_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO referrals(referrer_id, referee_id, created_at) VALUES(?,?,?)",
            (referrer_id, referee_id, now_str())
        )


def get_referral_by_referee(referee_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM referrals WHERE referee_id=?", (referee_id,)
        ).fetchone()


def get_referral_stats(referrer_id):
    """Return referral stats for a user."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=?", (referrer_id,)
        ).fetchone()["n"]
        # Count purchases by referees (only first purchase per referee)
        purchase_count = conn.execute(
            "SELECT COUNT(DISTINCT r.referee_id) AS n "
            "FROM referrals r "
            "JOIN purchases p ON p.user_id = r.referee_id AND p.is_test = 0 "
            "WHERE r.referrer_id=?",
            (referrer_id,)
        ).fetchone()["n"]
        total_purchase_amount = conn.execute(
            "SELECT COALESCE(SUM(sub.first_amount), 0) AS total FROM ("
            "  SELECT MIN(p.id) AS first_id, p.amount AS first_amount "
            "  FROM referrals r "
            "  JOIN purchases p ON p.user_id = r.referee_id AND p.is_test = 0 "
            "  WHERE r.referrer_id=? "
            "  GROUP BY r.referee_id"
            ") sub",
            (referrer_id,)
        ).fetchone()["total"]
        return {
            "total_referrals": total,
            "purchase_count": purchase_count,
            "total_purchase_amount": total_purchase_amount,
        }


def count_referrals(referrer_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=? AND captcha_failed=0",
            (referrer_id,)
        ).fetchone()["n"]


def get_referrals_paged(referrer_id, page=0, per_page=10):
    """Return paginated list of referrals with basic user info."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=? AND captcha_failed=0",
            (referrer_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT r.referee_id, u.full_name, u.username "
            "FROM referrals r "
            "LEFT JOIN users u ON u.user_id = r.referee_id "
            "WHERE r.referrer_id=? AND r.captcha_failed=0 ORDER BY r.id DESC LIMIT ? OFFSET ?",
            (referrer_id, per_page, page * per_page)
        ).fetchall()
    return rows, total


# ── Agency request message tracking ───────────────────────────────────────────────
def save_agency_request_message(referee_uid, chat_id, message_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO agency_request_messages (referee_uid, chat_id, message_id) VALUES (?,?,?)",
            (referee_uid, chat_id, message_id),
        )


def get_agency_request_messages(referee_uid):
    with get_conn() as conn:
        return conn.execute(
            "SELECT chat_id, message_id FROM agency_request_messages WHERE referee_uid=?",
            (referee_uid,),
        ).fetchall()


def delete_agency_request_messages(referee_uid):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM agency_request_messages WHERE referee_uid=?", (referee_uid,)
        )


# ── Reseller per-GB pricing ────────────────────────────────────────────────────
def get_per_gb_price(user_id, type_id):
    """Returns price_per_gb integer or None if not set."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT price_per_gb FROM reseller_per_gb_prices WHERE user_id=? AND type_id=?",
            (user_id, type_id)
        ).fetchone()
    return row["price_per_gb"] if row else None


def set_per_gb_price(user_id, type_id, price):
    from .helpers import now_str
    now = now_str()
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reseller_per_gb_prices (user_id, type_id, price_per_gb, created_at, updated_at) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(user_id, type_id) DO UPDATE SET price_per_gb=excluded.price_per_gb, updated_at=excluded.updated_at",
            (user_id, type_id, price, now, now)
        )


def get_all_per_gb_prices(user_id):
    """Returns list of rows with type_id and price_per_gb for a user."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT type_id, price_per_gb FROM reseller_per_gb_prices WHERE user_id=?",
            (user_id,)
        ).fetchall()


# ── Purchase addon prices ──────────────────────────────────────────────────────

def get_panel_connected_types():
    """Returns config_types that have at least one panel-linked package."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT DISTINCT ct.id, ct.name FROM config_types ct "
            "JOIN packages p ON p.type_id=ct.id "
            "WHERE p.config_source='panel' AND ct.is_active=1 "
            "ORDER BY ct.name"
        ).fetchall()


def get_addon_price(type_id, addon_type):
    """Returns the addon price row for a given type_id and addon_type, or None."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM purchase_addon_prices WHERE type_id=? AND addon_type=?",
            (type_id, addon_type)
        ).fetchone()


def set_addon_price(type_id, addon_type, role, unit_price):
    """Set normal or reseller unit price for a category addon.
    role: 'normal' | 'reseller'
    unit_price: integer or None to clear.
    """
    field = "normal_unit_price" if role == "normal" else "reseller_unit_price"
    with get_conn() as conn:
        # Try upsert — insert if not exists, then update the specific role column
        try:
            conn.execute(
                "INSERT INTO purchase_addon_prices(type_id, addon_type, created_at, updated_at) "
                "VALUES(?,?,?,?)",
                (type_id, addon_type, now_str(), now_str())
            )
        except Exception:
            pass
        conn.execute(
            f"UPDATE purchase_addon_prices SET {field}=?, updated_at=? WHERE type_id=? AND addon_type=?",
            (unit_price, now_str(), type_id, addon_type)
        )


def get_all_addon_prices_for_addon_type(addon_type):
    """Returns rows (type_id, type_name, normal_unit_price, reseller_unit_price)
    for all panel-connected types, joined with any existing price row."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT ct.id AS type_id, ct.name AS type_name, "
            "ap.normal_unit_price, ap.reseller_unit_price "
            "FROM config_types ct "
            "JOIN packages p ON p.type_id = ct.id AND p.config_source = 'panel' "
            "LEFT JOIN purchase_addon_prices ap "
            "       ON ap.type_id = ct.id AND ap.addon_type = ? "
            "WHERE ct.is_active = 1 "
            "GROUP BY ct.id "
            "ORDER BY ct.name",
            (addon_type,)
        ).fetchall()



def create_reseller_request(user_id, username, full_name, description):
    from .helpers import now_str
    now = now_str()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO reseller_requests (user_id, username, full_name, description, status, created_at, updated_at) "
            "VALUES (?,?,?,?,'pending',?,?)",
            (user_id, username, full_name, description, now, now)
        )
        return cur.lastrowid


def get_reseller_request(user_id, status=None):
    """Get the most recent request for a user, optionally filtered by status."""
    with get_conn() as conn:
        if status:
            return conn.execute(
                "SELECT * FROM reseller_requests WHERE user_id=? AND status=? ORDER BY id DESC LIMIT 1",
                (user_id, status)
            ).fetchone()
        return conn.execute(
            "SELECT * FROM reseller_requests WHERE user_id=? ORDER BY id DESC LIMIT 1",
            (user_id,)
        ).fetchone()


def get_pending_reseller_requests(page=0, per_page=10):
    offset = page * per_page
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM reseller_requests WHERE status='pending' ORDER BY created_at ASC LIMIT ? OFFSET ?",
            (per_page, offset)
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM reseller_requests WHERE status='pending'"
        ).fetchone()["n"]
    return rows, total


def get_reseller_request_by_id(request_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM reseller_requests WHERE id=?", (request_id,)
        ).fetchone()


def approve_reseller_request(request_id, reviewed_by):
    from .helpers import now_str
    now = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE reseller_requests SET status='approved', reviewed_at=?, reviewed_by=?, updated_at=? WHERE id=?",
            (now, reviewed_by, now, request_id)
        )


def reject_reseller_request(request_id, reviewed_by):
    from .helpers import now_str
    now = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE reseller_requests SET status='rejected', rejected_at=?, reviewed_at=?, reviewed_by=?, updated_at=? WHERE id=?",
            (now, now, reviewed_by, now, request_id)
        )


# ── Purchase credit ────────────────────────────────────────────────────────────
def set_user_purchase_credit(user_id, enabled, limit):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET purchase_credit_enabled=?, purchase_credit_limit=? WHERE user_id=?",
            (1 if enabled else 0, int(limit), user_id)
        )


def can_use_credit(user_id, amount):
    """Returns True if user can use purchase credit to cover `amount` (even with negative balance)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT balance, purchase_credit_enabled, purchase_credit_limit FROM users WHERE user_id=?",
            (user_id,)
        ).fetchone()
    if not row or not row["purchase_credit_enabled"]:
        return False
    # Can pay if balance + credit_limit >= amount
    return (row["balance"] + row["purchase_credit_limit"]) >= amount


# ── Payment admin message tracking ────────────────────────────────────────────
def save_payment_admin_message(payment_id, admin_id, message_id):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO payment_admin_messages (payment_id, admin_id, message_id) VALUES (?,?,?)",
            (payment_id, admin_id, message_id),
        )


def get_payment_admin_messages(payment_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT admin_id, message_id FROM payment_admin_messages WHERE payment_id=?",
            (payment_id,),
        ).fetchall()


def delete_payment_admin_messages(payment_id):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM payment_admin_messages WHERE payment_id=?", (payment_id,)
        )


def count_referee_first_purchases(referrer_id):
    """Count how many of referrer's referees have made at least one non-test purchase."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(DISTINCT r.referee_id) AS n "
            "FROM referrals r "
            "JOIN purchases p ON p.user_id = r.referee_id AND p.is_test = 0 "
            "WHERE r.referrer_id=? AND r.purchase_reward_given = 0",
            (referrer_id,)
        ).fetchone()["n"]


def set_referral_captcha_verified(referee_id: int) -> bool:
    """
    Atomically mark that a referee has passed captcha (0 → 1 transition).
    Returns True only if this call performed the transition (first time).
    Idempotent: safe to call multiple times.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE referrals SET captcha_verified=1 WHERE referee_id=? AND captcha_verified=0",
            (referee_id,)
        )
        return cur.rowcount > 0


def set_referral_captcha_failed(referee_id: int) -> bool:
    """
    Mark that a referee failed captcha (idempotent).
    Returns True if the row was updated (first failure record).
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE referrals SET captcha_failed=1 WHERE referee_id=? AND captcha_failed=0 AND captcha_verified=0",
            (referee_id,)
        )
        return cur.rowcount > 0


def set_referral_channel_joined(referee_id: int) -> bool:
    """
    Atomically mark that a referee has joined the channel (0 → 1 transition).
    Returns True only if this call performed the transition (first-ever join).
    Idempotent: safe to call multiple times.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE referrals SET channel_joined=1 WHERE referee_id=? AND channel_joined=0",
            (referee_id,)
        )
        return cur.rowcount > 0


def claim_invitee_reward(referee_id: int) -> bool:
    """
    Atomically mark invitee_reward_claimed 0→1 for a referee.
    Returns True only if this call performed the transition (first time).
    Idempotent: safe to call multiple times.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE referrals SET invitee_reward_claimed=1 "
            "WHERE referee_id=? AND invitee_reward_claimed=0",
            (referee_id,)
        )
        return cur.rowcount > 0


def try_claim_start_reward_batch(referrer_id: int, required_count: int,
                                  channel_required: bool,
                                  captcha_required: bool = False,
                                  phone_required: bool = False) -> bool:
    """
    Atomically claim `required_count` eligible unrewarded start-referrals.
    First checks if enough eligible rows exist; only then performs the UPDATE.
    Returns True if the batch was fully claimed (caller should now give the reward).
    Thread-safe against race conditions.
    captcha_required: if True, only count referees who have passed captcha verification.
    phone_required: if True, only count referees who have provided a phone number
        (used when phone gate is enabled to exclude users who never finished signup,
        e.g. those rejected because of an unaccepted phone number).
    """
    ch = "AND channel_joined=1" if channel_required else ""
    cp = "AND captcha_verified=1" if captcha_required else ""
    ph = (
        "AND EXISTS (SELECT 1 FROM users u "
        "WHERE u.user_id=referrals.referee_id "
        "AND u.phone_number IS NOT NULL AND TRIM(u.phone_number) <> '' "
        "AND (u.status IS NULL OR u.status <> 'restricted'))"
    ) if phone_required else ""
    with get_conn() as conn:
        count = conn.execute(
            f"SELECT COUNT(*) AS n FROM referrals "
            f"WHERE referrer_id=? AND start_reward_given=0 {ch} {cp} {ph}",
            (referrer_id,)
        ).fetchone()["n"]
        if count < required_count:
            return False
        cur = conn.execute(
            f"""UPDATE referrals
                   SET start_reward_given=1, rewarded_at=?
                 WHERE referrer_id=? AND start_reward_given=0 {ch} {cp} {ph}
                   AND referee_id IN (
                         SELECT referee_id FROM referrals
                          WHERE referrer_id=? AND start_reward_given=0 {ch} {cp} {ph}
                          LIMIT ?
                       )""",
            (now_str(), referrer_id, referrer_id, required_count)
        )
        return cur.rowcount >= required_count


def mark_start_reward_given(referrer_id, referee_ids):
    """Legacy helper kept for backwards-compat. Prefer try_claim_start_reward_batch."""
    with get_conn() as conn:
        for rid in referee_ids:
            conn.execute(
                "UPDATE referrals SET start_reward_given=1, rewarded_at=?"
                " WHERE referrer_id=? AND referee_id=? AND start_reward_given=0",
                (now_str(), referrer_id, rid)
            )


def mark_purchase_reward_given(referrer_id, referee_ids):
    with get_conn() as conn:
        for rid in referee_ids:
            conn.execute(
                "UPDATE referrals SET purchase_reward_given=1"
                " WHERE referrer_id=? AND referee_id=? AND purchase_reward_given=0",
                (referrer_id, rid)
            )


def get_unrewarded_start_referrals(referrer_id, channel_required: bool = False):
    """Get referral rows eligible for start reward (not yet rewarded)."""
    ch = "AND channel_joined=1" if channel_required else ""
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM referrals WHERE referrer_id=? AND start_reward_given=0 {ch}",
            (referrer_id,)
        ).fetchall()


def get_unrewarded_purchase_referees(referrer_id):
    """Get referee IDs who made first purchase but referrer hasn't been rewarded."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT DISTINCT r.referee_id FROM referrals r "
            "JOIN purchases p ON p.user_id = r.referee_id AND p.is_test = 0 "
            "WHERE r.referrer_id=? AND r.purchase_reward_given=0",
            (referrer_id,)
        ).fetchall()


# ── Voucher Batches & Codes ────────────────────────────────────────────────────
def add_voucher_batch(name, gift_type, gift_amount, package_id, codes):
    """Create a batch and insert all generated codes. Returns batch_id."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO voucher_batches(name, gift_type, gift_amount, package_id, total_count, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (name, gift_type, gift_amount, package_id, len(codes), now_str())
        )
        batch_id = conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]
        conn.executemany(
            "INSERT INTO voucher_codes(batch_id, code, is_used) VALUES(?,?,0)",
            [(batch_id, c) for c in codes]
        )
        return batch_id


def get_all_voucher_batches():
    with get_conn() as conn:
        return conn.execute(
            "SELECT vb.*, "
            "(SELECT COUNT(*) FROM voucher_codes WHERE batch_id=vb.id AND is_used=1) AS used_count "
            "FROM voucher_batches vb ORDER BY vb.id DESC"
        ).fetchall()


def get_voucher_batch(batch_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT vb.*, "
            "(SELECT COUNT(*) FROM voucher_codes WHERE batch_id=vb.id AND is_used=1) AS used_count "
            "FROM voucher_batches vb WHERE vb.id=?",
            (batch_id,)
        ).fetchone()


def get_voucher_codes_for_batch(batch_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM voucher_codes WHERE batch_id=? ORDER BY id ASC",
            (batch_id,)
        ).fetchall()


def get_voucher_code_by_code(code):
    with get_conn() as conn:
        return conn.execute(
            "SELECT vc.*, vb.gift_type, vb.gift_amount, vb.package_id, vb.name AS batch_name "
            "FROM voucher_codes vc JOIN voucher_batches vb ON vb.id=vc.batch_id "
            "WHERE LOWER(vc.code)=LOWER(?)",
            (code.strip(),)
        ).fetchone()


def redeem_voucher_code(code_id, user_id):
    """Mark a voucher code as used. Returns True if newly redeemed, False if already used."""
    with get_conn() as conn:
        result = conn.execute(
            "UPDATE voucher_codes SET is_used=1, used_by=?, used_at=? "
            "WHERE id=? AND is_used=0",
            (user_id, now_str(), code_id)
        )
        return result.rowcount > 0


def delete_voucher_batch(batch_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM voucher_batches WHERE id=?", (batch_id,))


# ── Panels (3x-ui / Sanaei) ───────────────────────────────────────────────────

def get_all_panels():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM panels ORDER BY id ASC"
        ).fetchall()


def get_active_panels():
    """Return only panels with is_active=1 (used by background checker)."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM panels WHERE is_active=1 ORDER BY id ASC"
        ).fetchall()


def get_panel(panel_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM panels WHERE id=?", (panel_id,)
        ).fetchone()


def add_panel(name, protocol, host, port, path, username, password, sub_url_base=""):
    ts = now_str()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO panels(name,protocol,host,port,path,username,password,sub_url_base,"
            "is_active,connection_status,last_checked_at,last_error,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?,1,'unknown','','',?,?)",
            (name.strip(), protocol, host.strip(), int(port),
             path.strip(), username.strip(), password,
             (sub_url_base or "").strip().rstrip("/"), ts, ts)
        )
        return cur.lastrowid


_PANEL_EDITABLE_FIELDS = {
    "name", "protocol", "host", "port", "path", "username", "password", "sub_url_base",
}


def update_panel_field(panel_id, field, value):
    if field not in _PANEL_EDITABLE_FIELDS:
        raise ValueError(f"Non-editable panel field: {field}")
    with get_conn() as conn:
        conn.execute(
            f"UPDATE panels SET {field}=?, updated_at=? WHERE id=?",
            (value, now_str(), panel_id)
        )


def toggle_panel_active(panel_id, is_active: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE panels SET is_active=?, updated_at=? WHERE id=?",
            (int(is_active), now_str(), panel_id)
        )


def update_panel_status(panel_id, status: str, error: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE panels SET connection_status=?, last_checked_at=?, last_error=? WHERE id=?",
            (status, now_str(), error, panel_id)
        )


def delete_panel(panel_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM panels WHERE id=?", (panel_id,))


# ── Package panel settings ─────────────────────────────────────────────────────
def update_package_panel_settings(package_id, config_source,
                                   panel_id=None, panel_type=None,
                                   panel_port=None, delivery_mode=None,
                                   client_package_id=None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE packages SET config_source=?, panel_id=?, panel_type=?,
               panel_port=?, delivery_mode=?, client_package_id=? WHERE id=?""",
            (config_source, panel_id, panel_type, panel_port, delivery_mode or 'config_only',
             client_package_id, package_id)
        )


# ── Panel Client Packages (config templates) ───────────────────────────────────
def add_panel_client_package(panel_id, inbound_id, delivery_mode,
                              sample_config="", sample_sub_url="", name=""):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO panel_client_packages
               (panel_id, inbound_id, delivery_mode, sample_config, sample_sub_url, name, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (panel_id, inbound_id, delivery_mode, sample_config or "", sample_sub_url or "",
             name or "", now_str())
        )
        return cur.lastrowid


def get_panel_client_packages(panel_id):
    conn = get_conn()
    return conn.execute(
        "SELECT * FROM panel_client_packages WHERE panel_id=? ORDER BY id",
        (panel_id,)
    ).fetchall()


def get_panel_client_package(cpkg_id):
    conn = get_conn()
    return conn.execute(
        "SELECT * FROM panel_client_packages WHERE id=?", (cpkg_id,)
    ).fetchone()


def get_panel_client_package_by_inbound(panel_id, inbound_id):
    """Auto-detect a client package by matching panel_id + inbound_id."""
    conn = get_conn()
    return conn.execute(
        "SELECT * FROM panel_client_packages WHERE panel_id=? AND inbound_id=? ORDER BY id LIMIT 1",
        (panel_id, inbound_id)
    ).fetchone()


def delete_panel_client_package(cpkg_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM panel_client_packages WHERE id=?", (cpkg_id,))


def update_panel_client_package_samples(cpkg_id, sample_config, sample_sub_url):
    with get_conn() as conn:
        conn.execute(
            "UPDATE panel_client_packages SET sample_config=?, sample_sub_url=? WHERE id=?",
            (sample_config or "", sample_sub_url or "", cpkg_id)
        )


def update_panel_client_package_field(cpkg_id, field, value):
    _ALLOWED = {"inbound_id", "sample_config", "sample_sub_url", "sample_client_name", "name", "delivery_mode"}
    if field not in _ALLOWED:
        raise ValueError(f"Invalid field: {field}")
    with get_conn() as conn:
        conn.execute(f"UPDATE panel_client_packages SET {field}=? WHERE id=?", (value, cpkg_id))



# ── Panel configs (auto-created by purchases) ──────────────────────────────────
def add_panel_config(user_id, package_id, panel_id, panel_type,
                     inbound_id, inbound_port, client_name, client_uuid,
                     client_sub_url, client_config_text, expire_at,
                     inbound_remark="", purchase_id=None, payment_id=None, cpkg_id=None, is_test=0,
                     inbound_protocol="", delivery_slot_index=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO panel_configs
               (user_id, package_id, panel_id, panel_type, inbound_id, inbound_port,
                client_name, client_uuid, client_sub_url, client_config_text,
                inbound_remark, expire_at, created_at, purchase_id, payment_id, cpkg_id, is_test,
                inbound_protocol, delivery_slot_index)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, package_id, panel_id, panel_type, inbound_id, inbound_port,
             client_name, client_uuid, client_sub_url, client_config_text,
             inbound_remark or "", expire_at, now_str(), purchase_id, payment_id, cpkg_id, int(is_test),
             inbound_protocol or "", delivery_slot_index)
        )
        return cur.lastrowid


def assign_panel_config_is_test(config_id, is_test=0):
    """Set the is_test flag for a panel config (kept for older call sites)."""
    with get_conn() as conn:
        conn.execute("UPDATE panel_configs SET is_test=? WHERE id=?", (int(is_test), config_id))


def get_panel_config(config_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM panel_configs WHERE id=?", (config_id,)
        ).fetchone()


def get_panel_configs_by_cpkg(cpkg_id):
    """Return all panel_configs that were created from the given client package template."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM panel_configs WHERE cpkg_id=? ORDER BY id",
            (cpkg_id,)
        ).fetchall()


def update_panel_config_texts(config_id, config_text, sub_url):
    """Update the rendered config text and sub URL of a sold panel_config (used after template rebuild)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE panel_configs SET client_config_text=?, client_sub_url=? WHERE id=?",
            (config_text or "", sub_url or "", config_id)
        )


def get_panel_configs(search=None, only_expired=False, filter_type=None,
                      package_id=None, page=0, per_page=10):
    """
    filter_type: 'all' | 'expiring' | 'expired'  (overrides only_expired)
    package_id : restrict to a specific package (None = all packages)
    """
    if filter_type is None:
        filter_type = "expired" if only_expired else "all"
    base = (
        "SELECT pc.*, u.full_name, u.username, "
        "p.name AS package_name, p.volume_gb, p.duration_days, p.price, p.type_id, "
        "t.name AS type_name "
        "FROM panel_configs pc "
        "LEFT JOIN users u ON pc.user_id=u.user_id "
        "LEFT JOIN packages p ON pc.package_id=p.id "
        "LEFT JOIN config_types t ON t.id=p.type_id"
    )
    wheres, params = [], []
    if filter_type == "expired":
        wheres.append("pc.is_expired=1")
    elif filter_type == "expiring":
        wheres.append("pc.is_expired=0")
        wheres.append("pc.expire_at IS NOT NULL")
        wheres.append("pc.expire_at > datetime('now')")
        wheres.append(
            "(julianday(pc.expire_at) - julianday('now')) < "
            "0.2 * CAST(CASE WHEN p.duration_days > 0 THEN p.duration_days ELSE 9999 END AS REAL)"
        )
    if package_id is not None:
        wheres.append("pc.package_id=?")
        params.append(package_id)
    if search:
        s = f"%{search}%"
        wheres.append(
            "(CAST(pc.user_id AS TEXT) LIKE ? OR pc.client_name LIKE ? "
            "OR p.name LIKE ? OR pc.client_config_text LIKE ? OR pc.client_sub_url LIKE ?)"
        )
        params += [s, s, s, s, s]
    sql = base
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    sql += " ORDER BY pc.id DESC LIMIT ? OFFSET ?"
    params += [per_page, page * per_page]
    with get_conn() as conn:
        return conn.execute(sql, params).fetchall()


def get_panel_configs_count(search=None, only_expired=False, filter_type=None, package_id=None):
    """
    filter_type: 'all' | 'expiring' | 'expired'  (overrides only_expired)
    package_id : restrict to a specific package (None = all packages)
    """
    if filter_type is None:
        filter_type = "expired" if only_expired else "all"
    base = (
        "SELECT COUNT(*) AS n FROM panel_configs pc "
        "LEFT JOIN packages p ON pc.package_id=p.id"
    )
    wheres, params = [], []
    if filter_type == "expired":
        wheres.append("pc.is_expired=1")
    elif filter_type == "expiring":
        wheres.append("pc.is_expired=0")
        wheres.append("pc.expire_at IS NOT NULL")
        wheres.append("pc.expire_at > datetime('now')")
        wheres.append(
            "(julianday(pc.expire_at) - julianday('now')) < "
            "0.2 * CAST(CASE WHEN p.duration_days > 0 THEN p.duration_days ELSE 9999 END AS REAL)"
        )
    if package_id is not None:
        wheres.append("pc.package_id=?")
        params.append(package_id)
    if search:
        s = f"%{search}%"
        wheres.append(
            "(CAST(pc.user_id AS TEXT) LIKE ? OR pc.client_name LIKE ? "
            "OR p.name LIKE ? OR pc.client_config_text LIKE ? OR pc.client_sub_url LIKE ?)"
        )
        params += [s, s, s, s, s]
    sql = base
    if wheres:
        sql += " WHERE " + " AND ".join(wheres)
    with get_conn() as conn:
        row = conn.execute(sql, params).fetchone()
        return row["n"] if row else 0


def get_panel_config_full(config_id):
    """Return one panel config joined with user, package, and type info."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT pc.*, u.full_name, u.username,
                   p.name AS package_name, p.volume_gb, p.duration_days, p.price, p.type_id,
                   t.name AS type_name
            FROM panel_configs pc
            LEFT JOIN users u ON pc.user_id = u.user_id
            LEFT JOIN packages p ON pc.package_id = p.id
            LEFT JOIN config_types t ON t.id = p.type_id
            WHERE pc.id = ?
            """,
            (config_id,)
        ).fetchone()


def get_user_panel_configs(user_id):
    """Return all panel configs for a user, joined with package and type info."""
    with get_conn() as conn:
        return conn.execute(
            """
            SELECT pc.*, p.name AS package_name, p.volume_gb, p.duration_days,
                   t.name AS type_name
            FROM panel_configs pc
            LEFT JOIN packages p ON pc.package_id = p.id
            LEFT JOIN config_types t ON t.id = p.type_id
            WHERE pc.user_id = ?
            ORDER BY pc.id DESC
            """,
            (user_id,)
        ).fetchall()


def update_panel_config_field(config_id, field, value):
    """Update a single allowed field in panel_configs."""
    _ALLOWED = {
        "client_uuid", "client_sub_url", "client_config_text",
        "expire_at", "is_expired", "auto_renew", "is_disabled",
        "client_name", "package_id", "panel_id", "inbound_protocol",
    }
    if field not in _ALLOWED:
        raise ValueError(f"update_panel_config_field: field {field!r} not allowed")
    with get_conn() as conn:
        conn.execute(f"UPDATE panel_configs SET {field}=? WHERE id=?", (value, config_id))


def get_orphaned_panel_config_groups():
    """
    Return list of dicts {panel_id, count} for panel_configs whose panel_id
    no longer exists in the panels table (orphaned after panel deletion).
    """
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT pc.panel_id, COUNT(*) AS cnt
            FROM panel_configs pc
            LEFT JOIN panels p ON pc.panel_id = p.id
            WHERE p.id IS NULL
            GROUP BY pc.panel_id
            ORDER BY cnt DESC
            """
        ).fetchall()
    return [{"panel_id": r["panel_id"], "count": r["cnt"]} for r in rows]


def reassign_panel_configs(old_panel_id, new_panel_id):
    """Move all panel_configs with old_panel_id to new_panel_id."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE panel_configs SET panel_id=? WHERE panel_id=?",
            (int(new_panel_id), int(old_panel_id))
        )


def adopt_all_orphaned_configs(new_panel_id):
    """
    Reassign ALL orphaned panel_configs (whose panel no longer exists) to new_panel_id.
    Returns the total number of configs adopted.
    """
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE panel_configs SET panel_id=?
            WHERE panel_id NOT IN (SELECT id FROM panels)
            """,
            (int(new_panel_id),)
        )
        return cur.rowcount


def delete_panel_config(config_id):
    """Permanently delete a panel config record."""
    with get_conn() as conn:
        conn.execute("DELETE FROM panel_configs WHERE id=?", (config_id,))


def get_unexpired_panel_configs():
    """Return all panel configs not yet marked expired."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM panel_configs WHERE is_expired=0"
        ).fetchall()


def mark_panel_config_expired(config_id):
    with get_conn() as conn:
        conn.execute("UPDATE panel_configs SET is_expired=1 WHERE id=?", (config_id,))


def mark_panel_config_notified(config_id):
    with get_conn() as conn:
        conn.execute("UPDATE panel_configs SET expired_notified=1 WHERE id=?", (config_id,))



def add_pending_reward(user_id: int, reward_type: str, amount: int = 0,
                       package_id=None, source: str = "start") -> None:
    """Queue a referral reward for the user to claim later."""
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO pending_rewards(user_id,reward_type,amount,package_id,source,claimed,created_at)"
            " VALUES(?,?,?,?,?,0,?)",
            (user_id, reward_type, amount, package_id, source, now_str())
        )


def get_unclaimed_rewards(user_id: int):
    """Return all unclaimed pending_rewards rows for this user."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_rewards WHERE user_id=? AND claimed=0 ORDER BY id ASC",
            (user_id,)
        ).fetchall()


def has_pending_rewards(user_id: int) -> bool:
    """Return True if the user has at least one unclaimed reward."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM pending_rewards WHERE user_id=? AND claimed=0 LIMIT 1",
            (user_id,)
        ).fetchone()
    return row is not None


def mark_rewards_claimed(user_id: int) -> int:
    """Mark all unclaimed rewards as claimed. Returns count of rows updated."""
    ts = now_str()
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE pending_rewards SET claimed=1, claimed_at=? WHERE user_id=? AND claimed=0",
            (ts, user_id)
        )
        return cur.rowcount


def mark_reward_claimed_by_id(reward_id: int) -> None:
    """Mark a single pending_reward row as claimed (only after successful delivery)."""
    ts = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_rewards SET claimed=1, claimed_at=? WHERE id=? AND claimed=0",
            (ts, reward_id)
        )


def get_pending_rewards_summary(user_id: int) -> dict:
    """Return totals of unclaimed rewards: wallet_total (int toman) and config_count (int)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT reward_type, amount FROM pending_rewards WHERE user_id=? AND claimed=0",
            (user_id,)
        ).fetchall()
    wallet_total = 0
    config_count = 0
    for row in rows:
        if row["reward_type"] == "wallet":
            wallet_total += int(row["amount"] or 0)
        else:
            config_count += 1
    return {"wallet_total": wallet_total, "config_count": config_count}


def try_claim_purchase_reward_batch(referrer_id: int, required_count: int,
                                     phone_required: bool = False) -> bool:
    """
    Atomically claim `required_count` eligible unrewarded purchase-referrals.
    First checks if enough eligible rows exist; only then performs the UPDATE.
    Returns True if the batch was fully claimed (caller should now give the reward).
    Thread-safe against race conditions.

    Eligibility rules (a referee counts as "having made a purchase" only if):
      - they have a real (non-test) purchase whose payment_method is NOT a gift
        (referral_gift / invitee_gift) and amount > 0, OR
      - they have a panel_config that was created from a real payment
        (payment_id IS NOT NULL — gift panel configs are created with payment_id=NULL)

    phone_required: if True, also require that the referee has a registered
        phone number and is not restricted (excludes accounts the bot rejected).
    """
    ph = (
        "AND EXISTS (SELECT 1 FROM users u "
        "WHERE u.user_id=r.referee_id "
        "AND u.phone_number IS NOT NULL AND TRIM(u.phone_number) <> '' "
        "AND (u.status IS NULL OR u.status <> 'restricted'))"
    ) if phone_required else ""
    real_purchase_clause = (
        "EXISTS (SELECT 1 FROM purchases p "
        "        WHERE p.user_id = r.referee_id "
        "          AND p.is_test = 0 "
        "          AND COALESCE(p.amount, 0) > 0 "
        "          AND COALESCE(p.payment_method, '') NOT IN "
        "              ('referral_gift','invitee_gift','referral_reward','gift'))"
        " OR EXISTS (SELECT 1 FROM panel_configs pc "
        "            WHERE pc.user_id = r.referee_id "
        "              AND COALESCE(pc.is_test, 0) = 0 "
        "              AND pc.payment_id IS NOT NULL)"
    )
    with get_conn() as conn:
        count = conn.execute(
            f"""SELECT COUNT(*) AS n FROM referrals r
                WHERE r.referrer_id=? AND r.purchase_reward_given=0
                  AND ({real_purchase_clause})
                  {ph}""",
            (referrer_id,)
        ).fetchone()["n"]
        if count < required_count:
            return False
        cur = conn.execute(
            f"""UPDATE referrals
                   SET purchase_reward_given=1
                 WHERE referrer_id=? AND purchase_reward_given=0
                   AND referee_id IN (
                         SELECT r.referee_id FROM referrals r
                          WHERE r.referrer_id=? AND r.purchase_reward_given=0
                            AND ({real_purchase_clause})
                            {ph}
                          LIMIT ?
                       )""",
            (referrer_id, referrer_id, required_count)
        )
        return cur.rowcount >= required_count


# ── Locked Channels (multi-channel join enforcement) ──────────────────────────
def get_locked_channels():
    """Return all locked channel rows."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM locked_channels ORDER BY id ASC"
        ).fetchall()


def add_locked_channel(channel_id: str, join_url: str = "") -> bool:
    """Add a channel to the locked list. Returns True if added, False if already exists."""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO locked_channels(channel_id, join_url, added_at) VALUES(?,?,?)",
                (channel_id.strip(), (join_url or "").strip(), now_str())
            )
            return True
        except Exception:
            return False


def remove_locked_channel(channel_id: str) -> None:
    """Remove a channel from the locked list by its channel_id string."""
    with get_conn() as conn:
        conn.execute("DELETE FROM locked_channels WHERE channel_id=?", (channel_id.strip(),))


def remove_locked_channel_by_id(row_id: int) -> None:
    """Remove a locked channel row by primary key."""
    with get_conn() as conn:
        conn.execute("DELETE FROM locked_channels WHERE id=?", (row_id,))


# ── Wallet Payment Exceptions ──────────────────────────────────────────────────

def wallet_pay_enabled_for(user_id: int) -> bool:
    """Return True if wallet payment is allowed for this user."""
    enabled = setting_get("wallet_pay_enabled", "1")
    if enabled == "1":
        return True
    # Globally disabled — check exceptions list
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM wallet_pay_exceptions WHERE user_id=?", (user_id,)
        ).fetchone()
    return row is not None


def get_wallet_pay_exceptions(page=0, per_page=10, search=None):
    """Return (rows, total) of wallet payment exception users."""
    with get_conn() as conn:
        base = (
            "FROM wallet_pay_exceptions e "
            "LEFT JOIN users u ON u.user_id = e.user_id"
        )
        params: list = []
        where = ""
        if search:
            s = f"%{search}%"
            where = " WHERE (CAST(e.user_id AS TEXT) LIKE ? OR u.username LIKE ? OR u.full_name LIKE ?)"
            params = [s, s, s]
        total = conn.execute(f"SELECT COUNT(*) AS n {base}{where}", params).fetchone()["n"]
        rows  = conn.execute(
            f"SELECT e.id, e.user_id, e.added_at, u.full_name, u.username "
            f"{base}{where} ORDER BY e.id DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page]
        ).fetchall()
    return rows, total


def add_wallet_pay_exception(user_id: int) -> bool:
    """Add user to wallet pay exceptions. Returns True if added, False if already exists."""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO wallet_pay_exceptions(user_id, added_at) VALUES(?,?)",
                (user_id, now_str())
            )
            return True
        except Exception:
            return False


def remove_wallet_pay_exception(row_id: int) -> None:
    """Remove a wallet pay exception row by primary key."""
    with get_conn() as conn:
        conn.execute("DELETE FROM wallet_pay_exceptions WHERE id=?", (row_id,))


# ── Referral Anti-Spam & Restrictions ─────────────────────────────────────────

def get_referral_restriction(user_id: int):
    """Return the referral restriction row for a user, or None."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM referral_restrictions WHERE user_id=?", (user_id,)
        ).fetchone()


def add_referral_restriction(user_id: int, restriction_type: str,
                              reason: str = "", added_by: int = 0) -> bool:
    """
    Insert or replace referral restriction.
    Returns True if a new row was created, False if an existing row was updated.
    """
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM referral_restrictions WHERE user_id=?", (user_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE referral_restrictions SET restriction_type=?, reason=?, added_by=?, added_at=? "
                "WHERE user_id=?",
                (restriction_type, reason, added_by, now_str(), user_id),
            )
            return False
        conn.execute(
            "INSERT INTO referral_restrictions(user_id, restriction_type, reason, added_by, added_at) "
            "VALUES(?,?,?,?,?)",
            (user_id, restriction_type, reason, added_by, now_str()),
        )
        return True


def remove_referral_restriction_by_id(row_id: int) -> "tuple[int, str]|None":
    """Remove restriction by primary key. Returns (user_id, restriction_type) or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, restriction_type FROM referral_restrictions WHERE id=?", (row_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM referral_restrictions WHERE id=?", (row_id,))
        return (row["user_id"], row["restriction_type"])


def remove_referral_restriction_by_user(user_id: int) -> "str|None":
    """Remove restriction by user_id. Returns old restriction_type or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT restriction_type FROM referral_restrictions WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute("DELETE FROM referral_restrictions WHERE user_id=?", (user_id,))
        return row["restriction_type"]


def toggle_referral_restriction_type(user_id: int) -> "str|None":
    """Toggle restriction_type between 'referral_only' and 'full'. Returns new type or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT restriction_type FROM referral_restrictions WHERE user_id=?", (user_id,)
        ).fetchone()
        if not row:
            return None
        new_type = "full" if row["restriction_type"] == "referral_only" else "referral_only"
        conn.execute(
            "UPDATE referral_restrictions SET restriction_type=? WHERE user_id=?",
            (new_type, user_id),
        )
        return new_type


def get_referral_restrictions_paged(page: int = 0, per_page: int = 10, search=None):
    """Return (rows, total) of referral restrictions joined with user info."""
    with get_conn() as conn:
        base = (
            "FROM referral_restrictions rr "
            "LEFT JOIN users u ON u.user_id = rr.user_id"
        )
        params: list = []
        where = ""
        if search:
            s = f"%{search}%"
            where = " WHERE (CAST(rr.user_id AS TEXT) LIKE ? OR u.username LIKE ? OR u.full_name LIKE ?)"
            params = [s, s, s]
        total = conn.execute(f"SELECT COUNT(*) AS n {base}{where}", params).fetchone()["n"]
        rows = conn.execute(
            f"SELECT rr.id, rr.user_id, rr.restriction_type, rr.reason, rr.added_at, "
            f"u.full_name, u.username "
            f"{base}{where} ORDER BY rr.id DESC LIMIT ? OFFSET ?",
            params + [per_page, page * per_page],
        ).fetchall()
        return rows, total


def has_referral_spam_event(user_id: int) -> bool:
    """Return True if this user was already flagged (avoid duplicate alerts)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM referral_spam_events WHERE user_id=?", (user_id,)
        ).fetchone()
        return row is not None


def record_referral_spam_event(user_id: int, action_taken: str) -> None:
    """Record that this user was flagged for spam (idempotent)."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO referral_spam_events(user_id, notified_at, action_taken) "
            "VALUES(?,?,?)",
            (user_id, now_str(), action_taken),
        )


def count_recent_referrals(referrer_id: int, window_seconds: int) -> int:
    """Count referrals created by referrer_id within the last window_seconds seconds."""
    import time as _time
    cutoff_ts = _time.time() - window_seconds
    # created_at is stored as ISO string; compare via unixepoch()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM referrals "
            "WHERE referrer_id=? AND UNIXEPOCH(created_at) >= ?",
            (referrer_id, int(cutoff_ts)),
        ).fetchone()
        return row["n"] if row else 0


# ── Payment Cards (multi-card management) ─────────────────────────────────────

def get_payment_cards(active_only: bool = False) -> list:
    """Return list of payment cards. Pass active_only=True to get only enabled cards."""
    with get_conn() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM payment_cards WHERE is_active=1 ORDER BY id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM payment_cards ORDER BY id ASC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_payment_card(card_id: int):
    """Return a single payment card row by id, or None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM payment_cards WHERE id=?", (card_id,)
        ).fetchone()
        return dict(row) if row else None


def add_payment_card(card_number: str, bank_name: str, holder_name: str) -> int:
    """Insert a new card. Returns the new row id."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO payment_cards (card_number, bank_name, holder_name, is_active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (card_number.strip(), bank_name.strip(), holder_name.strip(), now_str()),
        )
        return cur.lastrowid


def update_payment_card(card_id: int, card_number: str, bank_name: str, holder_name: str) -> None:
    """Update card details."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE payment_cards SET card_number=?, bank_name=?, holder_name=? WHERE id=?",
            (card_number.strip(), bank_name.strip(), holder_name.strip(), card_id),
        )


def toggle_payment_card_active(card_id: int) -> bool:
    """Toggle card active state. Returns the new is_active bool."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT is_active FROM payment_cards WHERE id=?", (card_id,)
        ).fetchone()
        if not row:
            return False
        new_state = 0 if row["is_active"] else 1
        conn.execute(
            "UPDATE payment_cards SET is_active=? WHERE id=?", (new_state, card_id)
        )
        return bool(new_state)


def delete_payment_card(card_id: int) -> None:
    """Delete a card permanently."""
    with get_conn() as conn:
        conn.execute("DELETE FROM payment_cards WHERE id=?", (card_id,))


def pick_card_for_payment():
    """Return one active card dict for the next payment.

    Uses round-robin rotation when gw_card_rotation_enabled=1 and multiple
    active cards exist. Falls back to the legacy payment_card/bank/owner
    settings when no rows exist in payment_cards. Returns None when nothing
    is configured.
    """
    cards = get_payment_cards(active_only=True)
    if cards:
        if len(cards) == 1 or setting_get("gw_card_rotation_enabled", "0") != "1":
            return cards[0]
        try:
            idx = int(setting_get("gw_card_rotation_index", "0") or "0") % len(cards)
        except (ValueError, ZeroDivisionError):
            idx = 0
        card = cards[idx]
        setting_set("gw_card_rotation_index", str((idx + 1) % len(cards)))
        return card
    # Legacy single-card fallback
    card_num = setting_get("payment_card", "")
    if not card_num:
        return None
    return {
        "id": 0,
        "card_number": card_num,
        "bank_name":   setting_get("payment_bank", ""),
        "holder_name": setting_get("payment_owner", ""),
        "is_active":   1,
    }


# ── Gateway Fee / Bonus ────────────────────────────────────────────────────────

def get_gateway_fee_amount(gw_name: str, base_amount: int) -> int:
    """Return the fee to add on top of base_amount for this gateway (0 if disabled)."""
    if setting_get(f"gw_{gw_name}_fee_enabled", "0") != "1":
        return 0
    fee_type = setting_get(f"gw_{gw_name}_fee_type", "fixed")
    try:
        fee_value = float(setting_get(f"gw_{gw_name}_fee_value", "0") or "0")
    except ValueError:
        return 0
    if fee_type == "pct":
        return round(base_amount * fee_value / 100)
    return round(fee_value)


def get_gateway_bonus_amount(gw_name: str, base_amount: int) -> int:
    """Return wallet bonus to credit after successful payment through this gateway (0 if disabled)."""
    if setting_get(f"gw_{gw_name}_bonus_enabled", "0") != "1":
        return 0
    bonus_type = setting_get(f"gw_{gw_name}_bonus_type", "fixed")
    try:
        bonus_value = float(setting_get(f"gw_{gw_name}_bonus_value", "0") or "0")
    except ValueError:
        return 0
    if bonus_type == "pct":
        return round(base_amount * bonus_value / 100)
    return round(bonus_value)


def apply_gateway_fee(gw_name: str, base_amount: int) -> int:
    """Return base_amount + fee for this gateway (fee-adjusted payable amount)."""
    return base_amount + get_gateway_fee_amount(gw_name, base_amount)


# ── Delivery Queue ─────────────────────────────────────────────────────────────

def ensure_delivery_slots(payment_id, user_id, package_id, quantity, service_names=None):
    """Ensure canonical per-item delivery slots exist for a panel payment."""
    if payment_id is None:
        return []
    qty = max(1, int(quantity or 1))
    names = service_names or []
    ts = now_str()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for i in range(qty):
            desired = names[i] if i < len(names) else None
            conn.execute(
                "INSERT OR IGNORE INTO delivery_slots"
                "(payment_id,user_id,package_id,slot_index,desired_name,status,created_at,updated_at)"
                " VALUES(?,?,?,?,?,'pending',?,?)",
                (payment_id, user_id, package_id, i, desired, ts, ts),
            )
            if desired:
                conn.execute(
                    "UPDATE delivery_slots SET desired_name=COALESCE(NULLIF(desired_name,''), ?), updated_at=? "
                    "WHERE payment_id=? AND slot_index=?",
                    (desired, ts, payment_id, i),
                )
        conn.commit()
    return get_delivery_slots(payment_id)


def get_delivery_slots(payment_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM delivery_slots WHERE payment_id=? ORDER BY slot_index ASC",
            (payment_id,),
        ).fetchall()


def get_delivery_slot(payment_id, slot_index):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM delivery_slots WHERE payment_id=? AND slot_index=?",
            (payment_id, slot_index),
        ).fetchone()


def mark_delivery_slot_creating(payment_id, slot_index, allow_queued=False):
    """Atomically claim a slot for creation. Returns True only for the winner."""
    ts = now_str()
    stale = datetime.now(_TZ_TEHRAN) - timedelta(minutes=15)
    stale_j = jdatetime.datetime.fromgregorian(datetime=stale).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if allow_queued:
            conn.execute(
                "UPDATE delivery_slots SET status='creating', updated_at=? "
                "WHERE payment_id=? AND slot_index=? AND "
                "(status IN ('pending','failed','queued') OR (status='creating' AND updated_at < ?))",
                (ts, payment_id, slot_index, stale_j),
            )
        else:
            conn.execute(
                "UPDATE delivery_slots SET status='creating', updated_at=? "
                "WHERE payment_id=? AND slot_index=? AND "
                "(status IN ('pending','failed') OR (status='creating' AND updated_at < ?))",
                (ts, payment_id, slot_index, stale_j),
            )
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.commit()
    return changed > 0


def mark_delivery_slot_delivered(payment_id, slot_index, panel_config_id):
    ts = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_slots SET status='delivered', panel_config_id=?, last_error=NULL, updated_at=? "
            "WHERE payment_id=? AND slot_index=?",
            (panel_config_id, ts, payment_id, slot_index),
        )


def mark_delivery_slot_queued(payment_id, slot_index, queue_id, error=None):
    ts = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_slots SET status='queued', queue_id=?, last_error=?, updated_at=? "
            "WHERE payment_id=? AND slot_index=? AND status!='delivered'",
            (queue_id, str(error)[:1000] if error else None, ts, payment_id, slot_index),
        )


def mark_delivery_slot_failed(payment_id, slot_index, error=None):
    ts = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_slots SET status='failed', last_error=?, updated_at=? "
            "WHERE payment_id=? AND slot_index=? AND status!='delivered'",
            (str(error)[:1000] if error else None, ts, payment_id, slot_index),
        )


def count_delivery_slots(payment_id):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM delivery_slots WHERE payment_id=? GROUP BY status",
            (payment_id,),
        ).fetchall()
    result = {"total": 0, "delivered": 0, "pending": 0, "creating": 0, "queued": 0, "failed": 0}
    for r in rows:
        st = r["status"] or "pending"
        n = int(r["n"] or 0)
        result[st] = n
        result["total"] += n
    return result


def get_missing_delivery_slots(payment_id, expected_qty):
    """Return slot indexes that do not exist or are neither delivered nor already queued/creating."""
    expected = max(1, int(expected_qty or 1))
    rows = get_delivery_slots(payment_id)
    by_idx = {int(r["slot_index"]): r for r in rows}
    missing = []
    for i in range(expected):
        r = by_idx.get(i)
        if not r or (r["status"] not in ("delivered", "queued", "creating")):
            missing.append(i)
    return missing


def get_completed_panel_payments_for_delivery_reconcile(limit=100, after_payment_id=0):
    """Return completed panel purchases that may still have missing delivery slots.

    This is used by the delivery worker after restarts.  A payment can be marked
    completed before immediate fulfillment creates/enqueues every slot; this
    query makes payments.quantity recoverable as the source of truth.

    ``after_payment_id`` is a hard watermark cutoff: only payments with
    ``id > after_payment_id`` are considered.  This prevents the worker from
    resurrecting old, already-delivered orders after a deploy.
    """
    try:
        cutoff = int(after_payment_id or 0)
    except Exception:
        cutoff = 0
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.* FROM payments p "
            "JOIN packages pk ON pk.id=p.package_id "
            "WHERE p.status='completed' "
            "AND p.kind='config_purchase' "
            "AND COALESCE(pk.config_source, 'manual')='panel' "
            "AND COALESCE(p.quantity, 1) > 0 "
            "AND p.id > ? "
            "ORDER BY COALESCE(p.fulfilled_at, p.approved_at, p.created_at) DESC "
            "LIMIT ?",
            (cutoff, int(limit or 100)),
        ).fetchall()
    return rows


def reset_delivery_cutoff_to_max_payment_id():
    """Cancel pending delivery work and move the reconcile cutoff to MAX(payments.id).

    Returns a dict with counts: queue_cancelled, slots_cancelled, new_cutoff.
    """
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE delivery_queue SET status='cancelled', last_error='reset by admin' "
            "WHERE status IN ('pending','retry','processing','creating','queued','failed')"
        )
        queue_cancelled = conn.execute("SELECT changes() AS c").fetchone()["c"]
        conn.execute(
            "UPDATE delivery_slots SET status='cancelled', last_error='reset by admin', updated_at=? "
            "WHERE status != 'delivered'",
            (now_str(),),
        )
        slots_cancelled = conn.execute("SELECT changes() AS c").fetchone()["c"]
        max_pid_row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM payments").fetchone()
        new_cutoff = int(max_pid_row[0] if max_pid_row else 0)
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('delivery_reconcile_after_payment_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(new_cutoff),),
        )
        conn.execute(
            "INSERT INTO settings(key,value) VALUES('delivery_reconcile_enabled','1') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )
        conn.commit()
    _invalidate_settings_cache()
    return {
        "queue_cancelled": int(queue_cancelled or 0),
        "slots_cancelled": int(slots_cancelled or 0),
        "new_cutoff": new_cutoff,
    }


def is_delivery_slot_stale(slot, stale_minutes=15):
    """Return True when a creating slot is old enough to be safely reclaimed."""
    if not slot:
        return True
    try:
        status = slot["status"]
    except Exception:
        status = None
    if status != "creating":
        return True
    try:
        updated = slot["updated_at"]
    except Exception:
        updated = None
    if not updated:
        return True
    stale = datetime.now(_TZ_TEHRAN) - timedelta(minutes=int(stale_minutes or 15))
    stale_j = jdatetime.datetime.fromgregorian(datetime=stale).strftime("%Y-%m-%d %H:%M:%S")
    return str(updated) < stale_j


def enqueue_delivery(user_id, chat_id, package_id, payment_id,
                     desired_name=None, unit_price=0, payment_method="", is_test=0,
                     slot_index=None):
    """Add a failed panel-config delivery to the persistent retry queue.

    Returns the new queue item id.
    """
    if payment_id is not None and slot_index is not None:
        return enqueue_delivery_once(
            user_id, chat_id, package_id, payment_id,
            desired_name=desired_name, unit_price=unit_price,
            payment_method=payment_method, is_test=is_test,
            slot_index=slot_index,
        )
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO delivery_queue"
            "(user_id,chat_id,package_id,payment_id,slot_index,desired_name,unit_price,"
            "payment_method,is_test,status,retry_count,created_at,next_retry_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,'pending',0,?,?)",
            (user_id, chat_id, package_id, payment_id, slot_index, desired_name, unit_price,
             payment_method, is_test, now_str(), now_str()),
        )
        return conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]


def enqueue_delivery_once(user_id, chat_id, package_id, payment_id,
                          desired_name=None, unit_price=0, payment_method="", is_test=0,
                          slot_index=None):
    """Enqueue one exact delivery slot, reusing an existing pending row if present."""
    if slot_index is None:
        return enqueue_delivery(user_id, chat_id, package_id, payment_id, desired_name, unit_price, payment_method, is_test)
    ts = now_str()
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT id FROM delivery_queue WHERE payment_id=? AND slot_index=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (payment_id, slot_index),
        ).fetchone()
        if existing:
            qid = existing["id"]
            conn.commit()
            return qid
        conn.execute(
            "INSERT INTO delivery_queue"
            "(user_id,chat_id,package_id,payment_id,slot_index,desired_name,unit_price,"
            "payment_method,is_test,status,retry_count,created_at,next_retry_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,'pending',0,?,?)",
            (user_id, chat_id, package_id, payment_id, slot_index, desired_name, unit_price,
             payment_method, is_test, ts, ts),
        )
        qid = conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]
        conn.commit()
        return qid


def get_due_deliveries():
    """Return all pending delivery_queue items whose next_retry_at <= now."""
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM delivery_queue WHERE status='pending' AND next_retry_at <= ?",
            (now_str(),),
        ).fetchall()


def update_delivery_retry(queue_id, error, next_retry_at):
    """Increment retry_count, store last_error, and schedule next attempt."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue"
            " SET retry_count=retry_count+1, last_error=?, next_retry_at=?, status='pending'"
            " WHERE id=?",
            (str(error)[:1000], next_retry_at, queue_id),
        )


def mark_delivery_delivered(queue_id, panel_config_id=None):
    """Mark a queue item as successfully delivered."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue"
            " SET status='delivered', delivered_at=?, panel_config_id=COALESCE(?,panel_config_id)"
            " WHERE id=?",
            (now_str(), panel_config_id, queue_id),
        )


def mark_delivery_failed(queue_id, error):
    """Mark a queue item as permanently failed (max retries exceeded)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue SET status='failed', last_error=? WHERE id=?",
            (str(error)[:1000], queue_id),
        )


def update_delivery_progress(queue_id, panel_config_id, client_uuid, client_name):
    """Persist partial-success state so the worker can skip re-creation on next attempt."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE delivery_queue"
            " SET panel_config_id=?, client_uuid=?, client_name=?"
            " WHERE id=?",
            (panel_config_id, client_uuid, client_name, queue_id),
        )


def get_delivery_queue_item(queue_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM delivery_queue WHERE id=?", (queue_id,)
        ).fetchone()


def fix_delivery_queue_gregorian_dates():
    """
    One-time migration: reset next_retry_at to now() for any delivery_queue
    items whose next_retry_at is in Gregorian format (starts with '20').
    These were written by the buggy delivery_worker that used UTC Gregorian
    instead of Jalali Tehran, causing them to never be picked up.
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM delivery_queue WHERE status='pending' AND next_retry_at LIKE '20%'"
        ).fetchall()
        if rows:
            ids = [r["id"] for r in rows]
            conn.execute(
                "UPDATE delivery_queue SET next_retry_at=? WHERE id IN ({})".format(
                    ",".join("?" * len(ids))
                ),
                [now_str()] + ids,
            )
    return len(rows) if rows else 0

