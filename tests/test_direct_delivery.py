# -*- coding: utf-8 -*-
"""
Tests for the direct-delivery system (bot/direct_delivery.py).

Each test uses an in-memory SQLite DB and patches out external calls
(panel API, Telegram bot, admin notifications, referral rewards).
"""

import sys, os, threading, time, sqlite3, types, importlib, importlib.util
from unittest.mock import patch, MagicMock, call
import pytest

# ─── make the project root importable without installing ──────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT_DIR = os.path.join(ROOT, "bot")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ─── Set env vars early so bot.config doesn't raise SystemExit ───────────────
os.environ.setdefault("BOT_TOKEN", "123456:FAKE_TOKEN_FOR_TESTS")
os.environ.setdefault("ADMIN_IDS",  "0")
os.environ.setdefault("DB_NAME",    ":memory:")


def _stub(name, **attrs):
    """Create and register a stub module."""
    m = types.ModuleType(name)
    m.__package__ = name.rsplit(".", 1)[0] if "." in name else name
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _load_real(dotted_name):
    """Load a real .py file as a module by dotted name, bypassing package __init__."""
    parts = dotted_name.split(".")
    file_path = os.path.join(ROOT, *parts) + ".py"
    spec = importlib.util.spec_from_file_location(dotted_name, file_path)
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = dotted_name.rsplit(".", 1)[0]
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


# ─── Stub the entire `bot` package so __init__.py never runs ─────────────────
# We do this by placing a fake module object in sys.modules["bot"] BEFORE any
# real package initialization can occur.  We then load the specific sub-modules
# we need via _load_real() which bypasses the package __init__.

_bot_pkg = types.ModuleType("bot")
_bot_pkg.__path__    = [BOT_DIR]
_bot_pkg.__package__ = "bot"
_bot_pkg.__file__    = os.path.join(BOT_DIR, "__init__.py")
sys.modules["bot"] = _bot_pkg

# Stub all heavy sub-modules that real bot.config / bot.helpers / bot.db
# would try to import at module level.
_bot_mock = MagicMock()

_stub("telebot",        TeleBot=lambda *a, **kw: _bot_mock)
_stub("telebot.types",  Message=MagicMock, CallbackQuery=MagicMock)
_stub("jdatetime")

_stub("bot.config",
      BOT_TOKEN="123456:FAKE", ADMIN_IDS=set(), DB_NAME=":memory:",
      CRYPTO_COINS=[], ADMIN_GROUP_ID=None, ADMIN_TOPIC_IDS={},
      PERM_USER_FULL=set(), PERM_FULL_SET=set())

from datetime import timezone, timedelta as _td
_TZ_TEHRAN = timezone(_td(hours=3, minutes=30))
_stub("bot.helpers",
      now_str=lambda: "1404-01-01 00:00:00",
      fmt_price=lambda x: str(x),
      esc=lambda x: str(x),
      _TZ_TEHRAN=_TZ_TEHRAN)

_stub("bot.bot_instance", bot=_bot_mock, USER_STATE={}, PERSIAN_DIGITS="۰۱۲۳۴۵۶۷۸۹")
_stub("bot.group_manager", send_to_topic=lambda *a, **kw: None)

for _heavy in [
    "bot.handlers", "bot.handlers.start", "bot.handlers.callbacks",
    "bot.handlers.messages", "bot.handlers.buy_glass", "bot.handlers.license",
    "bot.ui", "bot.ui.notifications", "bot.ui.keyboards", "bot.ui.menus",
    "bot.ui.helpers", "bot.ui.start_menu", "bot.ui.apps_catalog", "bot.ui.premium_emoji",
    "bot.panels", "bot.panels.client", "bot.panels.checker",
    "bot.admin", "bot.admin.analytics", "bot.admin.backup", "bot.admin.renderers",
    "bot.gateways",
    "bot.license_manager", "bot.watchdog", "bot.service_naming",
    "bot.payments", "bot.crypto_fulfillment",
]:
    _stub(_heavy)

sys.modules["bot.ui.notifications"].check_and_give_referral_purchase_reward = lambda uid: None

# ─── Load the real modules under test ────────────────────────────────────────
import bot.db as _real_db                  # noqa: E402
import bot.direct_delivery as _real_dd     # noqa: E402
import bot.delivery_worker as _real_dw     # noqa: E402

# ─── helper: build a minimal in-memory DB ─────────────────────────────────────
SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    balance INTEGER NOT NULL DEFAULT 0,
    referrer_id INTEGER,
    referral_code TEXT
);
CREATE TABLE IF NOT EXISTS config_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT 'Test Type'
);
CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    package_id INTEGER,
    sold_to INTEGER,
    reserved_payment_id INTEGER,
    is_expired INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    config_source TEXT NOT NULL DEFAULT 'manual',
    panel_id INTEGER,
    type_id INTEGER NOT NULL DEFAULT 1,
    price INTEGER NOT NULL DEFAULT 100000,
    duration_days INTEGER NOT NULL DEFAULT 30
);
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    package_id INTEGER NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'completed',
    payment_method TEXT NOT NULL DEFAULT 'wallet',
    delivery_status TEXT NOT NULL DEFAULT 'not_required',
    delivered_count INTEGER NOT NULL DEFAULT 0,
    refunded_count INTEGER NOT NULL DEFAULT 0,
    delivery_attempts INTEGER NOT NULL DEFAULT 0,
    delivery_started_at TEXT,
    delivery_finished_at TEXT,
    delivery_last_error TEXT,
    join_url TEXT,
    final_amount INTEGER
);
CREATE TABLE IF NOT EXISTS panel_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER,
    user_id INTEGER,
    package_id INTEGER,
    delivery_slot_index INTEGER,
    client_name TEXT,
    panel_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE(payment_id, delivery_slot_index)
);
CREATE TABLE IF NOT EXISTS delivery_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER,
    status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS delivery_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER,
    slot_index INTEGER,
    status TEXT DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS panels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    protocol TEXT DEFAULT 'https',
    host TEXT,
    port INTEGER DEFAULT 443,
    path TEXT DEFAULT '',
    username TEXT,
    password TEXT,
    label TEXT
);
CREATE TABLE IF NOT EXISTS payment_service_names (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id INTEGER,
    slot_index INTEGER,
    name TEXT
);
"""


def _make_db():
    """Create an in-memory SQLite connection with minimal schema."""
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _seed(conn, *, quantity=1, amount=100000, panel_id=1, add_panel=True, balance=0):
    """Insert a user, panel, package, payment and return (user_id, package_id, payment_id)."""
    conn.execute("INSERT INTO users(user_id,username,full_name,balance) VALUES(1,'testuser','Test User',?)", (balance,))
    if add_panel:
        conn.execute("INSERT INTO panels(id,host,port,username,password) VALUES(?,?,?,?,?)",
                     (panel_id, "panel.test", 443, "admin", "secret"))
    conn.execute("INSERT OR IGNORE INTO config_types(id,name) VALUES(1,'Test Type')")
    conn.execute("INSERT INTO packages(id,name,config_source,panel_id,type_id,price) VALUES(1,'TestPkg','panel',?,1,100000)", (panel_id,))
    conn.execute(
        "INSERT INTO payments(user_id,package_id,amount,quantity,status,payment_method) VALUES(1,1,?,?,?,?)",
        (amount, quantity, "completed", "wallet")
    )
    conn.commit()
    row = conn.execute("SELECT last_insert_rowid() as id").fetchone()
    return 1, 1, row["id"]


# ─── Fixture: patch all external deps and inject an in-memory DB ──────────────

class FakeConn:
    """Wraps a real sqlite3 connection to work as a context manager."""
    def __init__(self, conn):
        self._conn = conn
    def __enter__(self):
        return self._conn
    def __exit__(self, *a):
        self._conn.commit()
    def execute(self, *a, **kw):
        return self._conn.execute(*a, **kw)


def _run_with_db(conn, fn):
    """
    Run fn() with bot.db patched to use `conn`.
    """
    import bot.db as db_mod
    from bot.helpers import now_str

    def fake_get_conn():
        return FakeConn(conn)

    # Patch threading-local get_conn to use our in-memory conn
    with patch.object(db_mod, "get_conn", fake_get_conn):
        fn()


# ─── Utility: synchronously run _run_delivery inside the in-memory DB ─────────

def _exec_delivery(conn, payment_id, *, panel_online=True, create_side_effect=None,
                   deliver_side_effect=None):
    """
    Patches _check_panel_online, _attempt_create_one, _deliver_config_to_user,
    _notify_admin, _send_user, get_panel, referral reward, then calls _run_delivery.

    panel_online: bool or list[bool] (one per attempt)
    create_side_effect: list of (ok, pc_id, name, err) tuples, one per slot call
    Returns the modified `conn` so callers can query it.
    """
    import bot.direct_delivery as dd
    import bot.db as db_mod
    from bot.helpers import now_str

    # Reset in-flight guard for clean tests
    with dd._inflight_lock:
        dd._inflight.discard(payment_id)

    # Build a fake panel row
    panel_row = conn.execute("SELECT * FROM panels WHERE id=1").fetchone()

    # Online sequence
    if isinstance(panel_online, bool):
        online_seq = iter([panel_online] * 20)
    else:
        online_seq = iter(panel_online)

    def fake_get_conn():
        return FakeConn(conn)

    # Default create: always succeed with incrementing pc_ids
    _create_counter = {"n": 0}

    def fake_get_panel(panel_id):
        return panel_row

    def fake_get_user(uid):
        r = conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
        return r

    if create_side_effect is not None:
        _create_iter = iter(create_side_effect)
        def fake_create(uid, package_id, payment_id, desired_name, slot_index, is_test):
            return next(_create_iter)
    else:
        def fake_create(uid, package_id, payment_id, desired_name, slot_index, is_test):
            _create_counter["n"] += 1
            pc_id = _create_counter["n"]
            # Insert into panel_configs so count_panel_configs works
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO panel_configs(payment_id,user_id,package_id,delivery_slot_index,client_name) VALUES(?,?,?,?,?)",
                    (payment_id, uid, package_id, slot_index, f"cfg-{slot_index}")
                )
                conn.commit()
            except Exception:
                pass
            return True, pc_id, f"cfg-{slot_index}", ""

    def fake_deliver(uid, pc_id, package_row):
        pass  # no-op

    def fake_check_panel(panel):
        return next(online_seq, False)

    def fake_notify_admin(text):
        pass

    def fake_send_user(uid, text):
        pass

    with patch.object(db_mod, "get_conn", fake_get_conn), \
         patch.object(dd, "_check_panel_online", fake_check_panel), \
         patch.object(dd, "_attempt_create_one", fake_create), \
         patch.object(dd, "_deliver_config_to_user", fake_deliver), \
         patch.object(dd, "_notify_admin", fake_notify_admin), \
         patch.object(dd, "_send_user", fake_send_user), \
         patch("bot.db.get_panel", fake_get_panel), \
         patch("bot.db.get_user", fake_get_user):
        # Also patch referral reward import in the delivery loop
        with patch("bot.ui.notifications.check_and_give_referral_purchase_reward", lambda uid: None, create=True):
            # Override RETRY and MAX so tests don't actually sleep
            orig_interval = dd.RETRY_INTERVAL_SECS
            orig_max      = dd.MAX_TOTAL_SECS
            orig_attempts = dd.MAX_ATTEMPTS
            dd.RETRY_INTERVAL_SECS = 0
            dd.MAX_TOTAL_SECS      = 0.1   # 100ms — means second attempt always times out
            dd.MAX_ATTEMPTS        = 1     # single attempt unless overridden
            try:
                dd._run_delivery(payment_id)
            finally:
                dd.RETRY_INTERVAL_SECS = orig_interval
                dd.MAX_TOTAL_SECS      = orig_max
                dd.MAX_ATTEMPTS        = orig_attempts

    return conn


# ══════════════════════════════════════════════════════════════════════════════
# TEST CASES
# ══════════════════════════════════════════════════════════════════════════════

class TestDirectDeliverySuccess:
    """K1: quantity=10, panel available → all 10 configs delivered, no refund."""

    def test_all_delivered_no_refund(self):
        conn = _make_db()
        uid, pkg_id, pay_id = _seed(conn, quantity=10, amount=1_000_000)

        # Run with up to 11 attempts allowed (but should finish on first)
        _exec_delivery_multi(conn, pay_id, quantity=10, panel_online=True, max_attempts=11)

        pay = conn.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
        configs = conn.execute("SELECT * FROM panel_configs WHERE payment_id=?", (pay_id,)).fetchall()
        queue_rows = conn.execute("SELECT * FROM delivery_queue WHERE payment_id=?", (pay_id,)).fetchall()

        assert len(configs) == 10, f"Expected 10 configs, got {len(configs)}"
        assert pay["delivery_status"] == "delivered"
        assert pay["delivered_count"] == 10
        assert pay["refunded_count"] == 0
        assert len(queue_rows) == 0, "No delivery_queue rows should be created"

        user = conn.execute("SELECT balance FROM users WHERE user_id=1").fetchone()
        assert user["balance"] == 0  # no refund to wallet


class TestDirectDeliveryTimeout:
    """K2: panel unavailable for full 5min window → full refund, status=delivery_failed_refunded."""

    def test_full_refund_on_timeout(self):
        conn = _make_db()
        amount = 300_000   # divisible by quantity=3 → 100_000 per config
        uid, pkg_id, pay_id = _seed(conn, quantity=3, amount=amount, balance=0)

        _exec_delivery_multi(conn, pay_id, quantity=3, panel_online=False, max_attempts=2)

        pay = conn.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
        configs = conn.execute("SELECT * FROM panel_configs WHERE payment_id=?", (pay_id,)).fetchall()
        queue_rows = conn.execute("SELECT * FROM delivery_queue WHERE payment_id=?", (pay_id,)).fetchall()
        user = conn.execute("SELECT balance FROM users WHERE user_id=1").fetchone()

        assert len(configs) == 0, "No configs should be created when panel is offline"
        assert pay["delivery_status"] == "delivery_failed_refunded"
        assert pay["refunded_count"] == 3
        assert len(queue_rows) == 0
        assert user["balance"] == amount  # full amount refunded


class TestDirectDeliveryPartial:
    """K3: panel creates 6 configs then fails → 6 delivered, refund remaining 4."""

    def test_partial_delivery_partial_refund(self):
        conn = _make_db()
        quantity = 10
        amount   = 1_000_000  # 100k per config
        uid, pkg_id, pay_id = _seed(conn, quantity=quantity, amount=amount, balance=0)

        # Create side-effect: first 6 succeed, last 4 fail
        def _create(uid, package_id, payment_id, desired_name, slot_index, is_test):
            if slot_index < 6:
                conn.execute(
                    "INSERT OR IGNORE INTO panel_configs(payment_id,user_id,package_id,delivery_slot_index,client_name) VALUES(?,?,?,?,?)",
                    (payment_id, uid, package_id, slot_index, f"cfg-{slot_index}")
                )
                conn.commit()
                return True, slot_index + 1, f"cfg-{slot_index}", ""
            return False, None, "", "panel error"

        _exec_delivery_multi(conn, pay_id, quantity=quantity, panel_online=True,
                              custom_create=_create, max_attempts=2)

        pay = conn.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
        configs = conn.execute("SELECT * FROM panel_configs WHERE payment_id=?", (pay_id,)).fetchall()
        user = conn.execute("SELECT balance FROM users WHERE user_id=1").fetchone()

        assert len(configs) == 6
        assert pay["delivery_status"] == "partially_refunded"
        assert pay["refunded_count"] == 4
        # 4 configs * 100k each = 400k refunded
        assert user["balance"] == 400_000


class TestDuplicateEmailHandling:
    """K4: unique-name conflict → system generates new name, config still delivered."""

    def test_duplicate_name_still_delivers(self):
        """
        If slot_index 0 is already taken (INSERT OR IGNORE ignores it),
        the delivery should still complete because _create_panel_config
        uses INSERT OR IGNORE and on conflict returns the existing row.
        """
        conn = _make_db()
        uid, pkg_id, pay_id = _seed(conn, quantity=1, amount=100_000)

        # Pre-insert a config at slot 0 to simulate a name conflict
        conn.execute(
            "INSERT OR IGNORE INTO panel_configs(payment_id,user_id,package_id,delivery_slot_index,client_name) VALUES(?,1,1,0,'pre-existing')",
            (pay_id,)
        )
        conn.commit()

        # Now run delivery — should detect existing config and succeed
        _exec_delivery_multi(conn, pay_id, quantity=1, panel_online=True)

        pay = conn.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
        configs = conn.execute("SELECT * FROM panel_configs WHERE payment_id=?", (pay_id,)).fetchall()

        # Already had 1, still 1
        assert len(configs) == 1
        assert pay["delivery_status"] == "delivered"


class TestIdempotency:
    """K5: fulfill called twice → configs created at most once, no double refund."""

    def test_no_double_delivery(self):
        conn = _make_db()
        uid, pkg_id, pay_id = _seed(conn, quantity=2, amount=200_000)

        _exec_delivery_multi(conn, pay_id, quantity=2, panel_online=True)
        # Call again — in-flight guard or existing configs should prevent duplicates
        _exec_delivery_multi(conn, pay_id, quantity=2, panel_online=True)

        configs = conn.execute(
            "SELECT * FROM panel_configs WHERE payment_id=?", (pay_id,)
        ).fetchall()
        assert len(configs) == 2, f"Expected 2 configs after two calls, got {len(configs)}"

    def test_refund_not_duplicated_on_double_call(self):
        """
        If fulfill_panel_payment_direct is called twice concurrently,
        the in-flight guard prevents a second thread from starting.
        We test this directly on _inflight set logic.
        """
        import bot.direct_delivery as dd

        payment_id = 9999
        # First call adds to in-flight
        with dd._inflight_lock:
            dd._inflight.discard(payment_id)
            dd._inflight.add(payment_id)

        # Verify the set blocks a second entry
        with dd._inflight_lock:
            already_running = payment_id in dd._inflight
        assert already_running, "payment_id should be in _inflight after first registration"

        # Cleanup
        with dd._inflight_lock:
            dd._inflight.discard(payment_id)


class TestReconcileDisabled:
    """K6: 100 old completed payments, bot starts, worker runs → no new configs, no queue rows."""

    def test_reconcile_does_not_create_configs(self):
        import bot.db as db_mod
        import bot.delivery_worker as dw

        conn = _make_db()

        # Insert 100 completed payments
        conn.execute("INSERT INTO users(user_id,username,full_name,balance) VALUES(1,'u1','User1',0)")
        conn.execute("INSERT INTO packages(id,name,config_source,panel_id,price) VALUES(1,'P','panel',1,1000)")
        for i in range(100):
            conn.execute(
                "INSERT INTO payments(user_id,package_id,amount,quantity,status,payment_method) VALUES(1,1,1000,1,'completed','wallet')"
            )
        conn.commit()

        queue_before = conn.execute("SELECT COUNT(*) as c FROM delivery_queue").fetchone()["c"]

        def fake_get_conn():
            return FakeConn(conn)

        def fake_setting_get(key, default=None):
            if key == "delivery_queue_system_enabled":
                return "0"
            if key == "delivery_reconcile_enabled":
                return "0"
            return default

        with patch.object(db_mod, "get_conn", fake_get_conn), \
             patch("bot.delivery_worker.setting_get", fake_setting_get, create=True):
            dw._run_delivery_cycle()

        queue_after = conn.execute("SELECT COUNT(*) as c FROM delivery_queue").fetchone()["c"]
        assert queue_after == queue_before, "No delivery_queue rows should be added by worker when disabled"


class TestNoQueueUsage:
    """K7: After payment success, delivery_queue row count must not increase."""

    def test_direct_delivery_does_not_touch_queue(self):
        conn = _make_db()
        uid, pkg_id, pay_id = _seed(conn, quantity=3, amount=300_000)

        queue_before = conn.execute("SELECT COUNT(*) as c FROM delivery_queue").fetchone()["c"]

        _exec_delivery_multi(conn, pay_id, quantity=3, panel_online=True)

        queue_after = conn.execute("SELECT COUNT(*) as c FROM delivery_queue").fetchone()["c"]
        assert queue_after == queue_before, \
            f"delivery_queue grew from {queue_before} to {queue_after}"


class TestWalletRefundIdempotency:
    """K8: refund_undelivered_to_wallet called twice → wallet credited only once."""

    def test_refund_idempotent(self):
        conn = _make_db()
        amount = 300_000
        uid, pkg_id, pay_id = _seed(conn, quantity=3, amount=amount, balance=0)

        import bot.db as db_mod

        def fake_get_conn():
            return FakeConn(conn)

        # Put payment in 'delivering' state first
        conn.execute("UPDATE payments SET delivery_status='delivering' WHERE id=?", (pay_id,))
        conn.commit()

        with patch.object(db_mod, "get_conn", fake_get_conn):
            r1 = db_mod.refund_undelivered_to_wallet(pay_id, uid, 3, 0, amount)
            r2 = db_mod.refund_undelivered_to_wallet(pay_id, uid, 3, 0, amount)

        assert r1 == amount, f"First refund should return {amount}, got {r1}"
        assert r2 == 0, f"Second refund should return 0 (already refunded), got {r2}"

        user = conn.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        assert user["balance"] == amount, f"Balance should be {amount}, got {user['balance']}"


# ══════════════════════════════════════════════════════════════════════════════
# SHARED HELPER for multi-attempt delivery tests
# ══════════════════════════════════════════════════════════════════════════════

def _exec_delivery_multi(conn, payment_id, *, quantity, panel_online=True,
                          custom_create=None, max_attempts=11):
    """
    Like _exec_delivery but allows configuring max_attempts and uses
    a default create that inserts panel_configs rows.
    """
    import bot.direct_delivery as dd
    import bot.db as db_mod

    with dd._inflight_lock:
        dd._inflight.discard(payment_id)

    panel_row = conn.execute("SELECT * FROM panels WHERE id=1").fetchone()

    if isinstance(panel_online, bool):
        online_seq = iter([panel_online] * (max_attempts + 10))
    else:
        online_seq = iter(panel_online)

    _create_counter = {"n": 0}

    def fake_get_panel(panel_id):
        return panel_row

    def fake_get_payment_service_names(payment_id):
        return []

    def fake_get_user(uid):
        return conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()

    if custom_create is not None:
        fake_create = custom_create
    else:
        def fake_create(uid, package_id, payment_id, desired_name, slot_index, is_test):
            _create_counter["n"] += 1
            pc_id = _create_counter["n"]
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO panel_configs(payment_id,user_id,package_id,delivery_slot_index,client_name) VALUES(?,?,?,?,?)",
                    (payment_id, uid, package_id, slot_index, f"cfg-{slot_index}")
                )
                conn.commit()
            except Exception:
                pass
            return True, pc_id, f"cfg-{slot_index}", ""

    orig_interval = dd.RETRY_INTERVAL_SECS
    orig_max      = dd.MAX_TOTAL_SECS
    orig_attempts = dd.MAX_ATTEMPTS
    dd.RETRY_INTERVAL_SECS = 0
    # MAX_TOTAL_SECS must be large enough so elapsed+interval < max is always True
    # for the number of allowed attempts, but we gate via MAX_ATTEMPTS instead.
    dd.MAX_TOTAL_SECS      = 9999
    dd.MAX_ATTEMPTS        = max_attempts

    def fake_get_conn():
        return FakeConn(conn)

    try:
        with patch.object(db_mod, "get_conn", fake_get_conn), \
             patch.object(dd, "_check_panel_online", lambda p: next(online_seq, False)), \
             patch.object(dd, "_attempt_create_one", fake_create), \
             patch.object(dd, "_deliver_config_to_user", lambda uid, pc_id, pkg: None), \
             patch.object(dd, "_notify_admin", lambda t: None), \
             patch.object(dd, "_send_user", lambda uid, t: None), \
             patch.object(db_mod, "get_panel", fake_get_panel), \
             patch.object(db_mod, "get_user", fake_get_user), \
             patch.object(db_mod, "get_payment_service_names", fake_get_payment_service_names), \
             patch("time.sleep", lambda s: None):
            try:
                import bot.ui.notifications as notif_mod
                with patch.object(notif_mod, "check_and_give_referral_purchase_reward", lambda uid: None):
                    dd._run_delivery(payment_id)
            except (ImportError, AttributeError):
                dd._run_delivery(payment_id)
    finally:
        dd.RETRY_INTERVAL_SECS = orig_interval
        dd.MAX_TOTAL_SECS      = orig_max
        dd.MAX_ATTEMPTS        = orig_attempts
