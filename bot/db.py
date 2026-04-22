# -*- coding: utf-8 -*-
import json
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timedelta

from .config import DB_NAME, CRYPTO_COINS
from .helpers import now_str


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
            "support_link":     "",
            "support_link_desc": "",
            "start_text":       "",
            "channel_id":       "",
            "backup_enabled":   "0",
            "backup_interval":  "24",
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

        ]
        for sql in indexes:
            try:
                conn.execute(sql)
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


def get_users(has_purchase=None, limit=None, offset=0, status=None):
    q = (
        "SELECT u.*, "
        "(SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id) AS purchase_count "
        "FROM users u WHERE 1=1"
    )
    params = []
    if has_purchase is True:
        q += " AND EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=u.user_id)"
    elif has_purchase is False:
        q += " AND NOT EXISTS (SELECT 1 FROM purchases p WHERE p.user_id=u.user_id)"
    if status is not None:
        q += " AND u.status=?"
        params.append(status)
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
                   (SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id) AS purchase_count,
                   (SELECT COALESCE(SUM(amount),0) FROM purchases p WHERE p.user_id=u.user_id) AS total_spent,
                   (SELECT COUNT(*) FROM payments py WHERE py.user_id=u.user_id AND py.kind='renewal' AND py.status='completed') AS renewal_count,
                   (SELECT COALESCE(SUM(amount),0) FROM payments py WHERE py.user_id=u.user_id AND py.kind='renewal' AND py.status='completed') AS total_renewals,
                   (SELECT COALESCE(SUM(py2.amount),0) FROM payments py2 WHERE py2.user_id=u.user_id AND py2.status='completed' AND py2.payment_method != 'wallet') AS total_direct_payments
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
            "SELECT COUNT(DISTINCT user_id) AS n FROM purchases"
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
            "(SELECT COUNT(*) FROM purchases p WHERE p.user_id=u.user_id) AS purchase_count "
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
    """Count users for a given filter type ('all', 'public', 'agents')."""
    with get_conn() as conn:
        if filter_type == "all":
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if filter_type == "public":
            return conn.execute("SELECT COUNT(*) FROM users WHERE is_agent=0").fetchone()[0]
        if filter_type == "agents":
            return conn.execute("SELECT COUNT(*) FROM users WHERE is_agent=1").fetchone()[0]
    return 0


# ── Config Types ───────────────────────────────────────────────────────────────
def get_all_types():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM config_types ORDER BY id DESC"
        ).fetchall()


def get_active_types():
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM config_types WHERE is_active=1 ORDER BY id DESC"
        ).fetchall()


def get_type(type_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM config_types WHERE id=?", (type_id,)
        ).fetchone()


def add_type(name, description=""):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO config_types(name, description) VALUES(?, ?)",
            (name.strip(), description.strip())
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


def delete_type(type_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM config_types WHERE id=?", (type_id,))


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


def add_package(type_id, name, volume_gb, duration_days, price, show_name=1, max_users=0, buyer_role='all'):
    with get_conn() as conn:
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(position),0) FROM packages WHERE type_id=?", (type_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO packages(type_id,name,volume_gb,duration_days,price,active,position,show_name,max_users,buyer_role)"
            " VALUES(?,?,?,?,?,1,?,?,?,?)",
            (type_id, name.strip(), volume_gb, duration_days, price, max_pos + 1, show_name, max_users, buyer_role)
        )


def toggle_package_active(package_id):
    with get_conn() as conn:
        conn.execute(
            "UPDATE packages SET active=((active+1)%2) WHERE id=?", (package_id,)
        )


def update_package_field(package_id, field, value):
    allowed = {"name", "volume_gb", "duration_days", "price", "position", "show_name", "max_users", "buyer_role"}
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
def add_config(type_id, package_id, service_name, config_text, inquiry_link):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO configs(type_id,package_id,service_name,config_text,"
            "inquiry_link,created_at) VALUES(?,?,?,?,?,?)",
            (type_id, package_id, service_name.strip(),
             config_text.strip(), inquiry_link.strip(), now_str())
        )


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
    return row["n"] > 0


def reset_all_free_tests():
    with get_conn() as conn:
        conn.execute("DELETE FROM purchases WHERE is_test=1")


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
    return row["cnt"] if row else 0


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
def create_payment(kind, user_id, package_id, amount, payment_method,
                   status="pending", config_id=None, crypto_coin=None, final_amount=None, quantity=1):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO payments(kind,user_id,package_id,amount,payment_method,"
            "status,created_at,config_id,crypto_coin,final_amount,quantity) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (kind, user_id, package_id, amount, payment_method,
             status, now_str(), config_id, crypto_coin, final_amount, max(1, int(quantity or 1)))
        )
        return conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]


def update_payment_final_amount(payment_id, final_amount):
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET final_amount=? WHERE id=?",
            (final_amount, payment_id)
        )


def get_payment(payment_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM payments WHERE id=?", (payment_id,)
        ).fetchone()


def get_pending_payments_page(page=0, page_size=10):
    """Return (total_count, list_of_dicts) for pending payments, oldest first."""
    offset = page * page_size
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM payments WHERE status='pending'"
        ).fetchone()["c"]
        rows = conn.execute(
            "SELECT p.*, u.full_name, u.username,"
            " pk.name AS pkg_name, t.name AS type_name, pk.volume_gb, pk.duration_days"
            " FROM payments p"
            " LEFT JOIN users u ON u.user_id = p.user_id"
            " LEFT JOIN packages pk ON pk.id = p.package_id"
            " LEFT JOIN config_types t ON t.id = pk.type_id"
            " WHERE p.status = 'pending'"
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


def complete_payment(payment_id):
    """Mark payment completed. Returns True if this call won the race, False if already processed."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE payments SET status='completed', approved_at=? WHERE id=? AND status IN ('pending', 'approved')",
            (now_str(), payment_id)
        )
        changed = conn.execute("SELECT changes() AS c").fetchone()["c"]
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


def add_discount_code(code, discount_type, discount_value, max_uses_total, max_uses_per_user, audience="all", scope_type="all"):
    audience = audience if audience in ("all", "public", "agents") else "all"
    scope_type = scope_type if scope_type in ("all", "types", "packages") else "all"
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO discount_codes(code, discount_type, discount_value, "
            "max_uses_total, max_uses_per_user, used_count, is_active, created_at, audience, scope_type) "
            "VALUES(?,?,?,?,?,0,1,?,?,?)",
            (code.strip().upper(), discount_type, int(discount_value),
             int(max_uses_total), int(max_uses_per_user), now_str(), audience, scope_type)
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


def validate_discount_code(code, user_id, amount, is_agent=False, package_id=None):
    """Returns (ok, row, discount_amount, final_amount, error_msg)."""
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
    # Scope check
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
    """Reject all pending payments. Returns count of rejected payments."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id FROM payments WHERE status='pending'"
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.execute(
                "UPDATE payments SET status='rejected', admin_note=?, approved_at=? "
                "WHERE status='pending'",
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
            "SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=?", (referrer_id,)
        ).fetchone()["n"]


def get_referrals_paged(referrer_id, page=0, per_page=10):
    """Return paginated list of referrals with basic user info."""
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=?", (referrer_id,)
        ).fetchone()["n"]
        rows = conn.execute(
            "SELECT r.referee_id, u.full_name, u.username "
            "FROM referrals r "
            "LEFT JOIN users u ON u.user_id = r.referee_id "
            "WHERE r.referrer_id=? ORDER BY r.id DESC LIMIT ? OFFSET ?",
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


def try_claim_start_reward_batch(referrer_id: int, required_count: int,
                                  channel_required: bool) -> bool:
    """
    Atomically claim `required_count` eligible unrewarded start-referrals.
    First checks if enough eligible rows exist; only then performs the UPDATE.
    Returns True if the batch was fully claimed (caller should now give the reward).
    Thread-safe against race conditions.
    """
    ch = "AND channel_joined=1" if channel_required else ""
    with get_conn() as conn:
        count = conn.execute(
            f"SELECT COUNT(*) AS n FROM referrals WHERE referrer_id=? AND start_reward_given=0 {ch}",
            (referrer_id,)
        ).fetchone()["n"]
        if count < required_count:
            return False
        cur = conn.execute(
            f"""UPDATE referrals
                   SET start_reward_given=1, rewarded_at=?
                 WHERE referrer_id=? AND start_reward_given=0 {ch}
                   AND referee_id IN (
                         SELECT referee_id FROM referrals
                          WHERE referrer_id=? AND start_reward_given=0 {ch}
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
            (config_source, panel_id, panel_type, panel_port, delivery_mode,
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
                     inbound_remark="", purchase_id=None, payment_id=None, cpkg_id=None):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO panel_configs
               (user_id, package_id, panel_id, panel_type, inbound_id, inbound_port,
                client_name, client_uuid, client_sub_url, client_config_text,
                inbound_remark, expire_at, created_at, purchase_id, payment_id, cpkg_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (user_id, package_id, panel_id, panel_type, inbound_id, inbound_port,
             client_name, client_uuid, client_sub_url, client_config_text,
             inbound_remark or "", expire_at, now_str(), purchase_id, payment_id, cpkg_id)
        )
        return cur.lastrowid


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
        "client_name", "package_id",
    }
    if field not in _ALLOWED:
        raise ValueError(f"update_panel_config_field: field {field!r} not allowed")
    with get_conn() as conn:
        conn.execute(f"UPDATE panel_configs SET {field}=? WHERE id=?", (value, config_id))


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


def try_claim_purchase_reward_batch(referrer_id: int, required_count: int) -> bool:
    """
    Atomically claim `required_count` eligible unrewarded purchase-referrals.
    First checks if enough eligible rows exist; only then performs the UPDATE.
    Returns True if the batch was fully claimed (caller should now give the reward).
    Thread-safe against race conditions.
    """
    with get_conn() as conn:
        count = conn.execute(
            """SELECT COUNT(*) AS n FROM referrals r
                WHERE r.referrer_id=? AND r.purchase_reward_given=0
                  AND (
                      EXISTS (SELECT 1 FROM purchases p
                              WHERE p.user_id = r.referee_id AND p.is_test = 0)
                      OR EXISTS (SELECT 1 FROM panel_configs pc
                                 WHERE pc.user_id = r.referee_id)
                  )""",
            (referrer_id,)
        ).fetchone()["n"]
        if count < required_count:
            return False
        cur = conn.execute(
            """UPDATE referrals
                   SET purchase_reward_given=1
                 WHERE referrer_id=? AND purchase_reward_given=0
                   AND referee_id IN (
                         SELECT r.referee_id FROM referrals r
                          WHERE r.referrer_id=? AND r.purchase_reward_given=0
                            AND (
                                EXISTS (SELECT 1 FROM purchases p
                                        WHERE p.user_id = r.referee_id AND p.is_test = 0)
                                OR EXISTS (SELECT 1 FROM panel_configs pc
                                           WHERE pc.user_id = r.referee_id)
                            )
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


def add_locked_channel(channel_id: str) -> bool:
    """Add a channel to the locked list. Returns True if added, False if already exists."""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO locked_channels(channel_id, added_at) VALUES(?,?)",
                (channel_id.strip(), now_str())
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
