# -*- coding: utf-8 -*-
"""
Tests for the delivery reconcile cutoff/watermark.

Run from project root:
    python -m unittest tests.test_delivery_cutoff
"""
import os
import tempfile
import unittest

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

from bot import config as bot_config
from bot import db
from bot import delivery_worker


class _TempDBMixin:
    def _new_db(self):
        tmp = tempfile.NamedTemporaryFile(prefix="delivery-cutoff-", suffix=".db", delete=False)
        tmp.close()
        bot_config.DB_NAME = tmp.name
        db.DB_NAME = tmp.name
        old_conn = getattr(db._tls, "conn", None)
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                pass
            db._tls.conn = None
        db._invalidate_settings_cache()
        return tmp

    def _close_db(self, tmp):
        old_conn = getattr(db._tls, "conn", None)
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                pass
            db._tls.conn = None
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    def _make_panel_package(self, uid):
        with db.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id,full_name,username,balance,joined_at,last_seen_at) "
                "VALUES(?,?,?,?,?,?)",
                (uid, "Test User", "test", 0, db.now_str(), db.now_str()),
            )
            conn.execute("INSERT INTO config_types(name,description,is_active) VALUES('Panel','',1)")
            type_id = conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]
            conn.execute(
                "INSERT INTO packages(type_id,name,volume_gb,duration_days,price,active) VALUES(?,?,?,?,?,1)",
                (type_id, "Panel package", 10, 30, 1000),
            )
            package_id = conn.execute("SELECT last_insert_rowid() AS x").fetchone()["x"]
            conn.execute(
                "UPDATE packages SET config_source='panel', panel_id=1, panel_port=1, "
                "panel_type='sanaei', delivery_mode='config_only' WHERE id=?",
                (package_id,),
            )
        return package_id

    def _seed_completed_payment(self, uid, package_id, quantity=1):
        return db.create_payment(
            "config_purchase", uid, package_id, 1000 * quantity,
            "test", status="completed", quantity=quantity,
        )


class DeliveryCutoffTests(_TempDBMixin, unittest.TestCase):
    def test_existing_db_seeds_cutoff_to_max_payment_id(self):
        tmp = self._new_db()
        try:
            # Pre-create schema then insert payments before init re-runs.
            db.init_db()
            uid = 1001
            package_id = self._make_panel_package(uid)
            for _ in range(3):
                self._seed_completed_payment(uid, package_id, quantity=2)
            # Force the watermark to be unset to simulate a pre-existing DB
            # being upgraded by this code for the first time.
            with db.get_conn() as conn:
                conn.execute("DELETE FROM settings WHERE key='delivery_reconcile_after_payment_id'")
            db._invalidate_settings_cache()
            # Re-run init to apply the watermark seed.
            db.init_db()
            cutoff = int(db.setting_get("delivery_reconcile_after_payment_id", "0") or "0")
            with db.get_conn() as conn:
                max_pid = conn.execute("SELECT MAX(id) AS m FROM payments").fetchone()["m"]
            self.assertEqual(cutoff, int(max_pid))
            # No old payment is returned for reconcile when cutoff equals MAX(id).
            rows = db.get_completed_panel_payments_for_delivery_reconcile(after_payment_id=cutoff)
            self.assertEqual(rows, [])
        finally:
            self._close_db(tmp)

    def test_new_db_cutoff_zero_allows_new_payments(self):
        tmp = self._new_db()
        try:
            db.init_db()
            cutoff = int(db.setting_get("delivery_reconcile_after_payment_id", "0") or "0")
            self.assertEqual(cutoff, 0)
            uid = 2002
            package_id = self._make_panel_package(uid)
            new_pid = self._seed_completed_payment(uid, package_id, quantity=2)
            self.assertGreater(new_pid, 0)
            rows = db.get_completed_panel_payments_for_delivery_reconcile(after_payment_id=cutoff)
            self.assertTrue(any(r["id"] == new_pid for r in rows))
        finally:
            self._close_db(tmp)

    def test_payment_id_at_or_below_cutoff_is_ignored(self):
        tmp = self._new_db()
        try:
            db.init_db()
            uid = 3003
            package_id = self._make_panel_package(uid)
            old_pid = self._seed_completed_payment(uid, package_id, quantity=1)
            db.setting_set("delivery_reconcile_after_payment_id", str(old_pid))
            rows = db.get_completed_panel_payments_for_delivery_reconcile(after_payment_id=old_pid)
            self.assertEqual([r["id"] for r in rows], [])
        finally:
            self._close_db(tmp)

    def test_payment_id_above_cutoff_is_reconciled(self):
        tmp = self._new_db()
        try:
            db.init_db()
            uid = 4004
            package_id = self._make_panel_package(uid)
            base_pid = self._seed_completed_payment(uid, package_id, quantity=1)
            db.setting_set("delivery_reconcile_after_payment_id", str(base_pid))
            new_pid = self._seed_completed_payment(uid, package_id, quantity=3)
            rows = db.get_completed_panel_payments_for_delivery_reconcile(after_payment_id=base_pid)
            self.assertEqual([r["id"] for r in rows], [new_pid])
            # Run the worker reconcile path; it must enqueue the 3 missing slots.
            delivery_worker._reconcile_completed_panel_payments(after_payment_id=base_pid)
            with db.get_conn() as conn:
                queued = conn.execute(
                    "SELECT COUNT(*) AS c FROM delivery_queue WHERE payment_id=? AND status='pending'",
                    (new_pid,),
                ).fetchone()["c"]
            self.assertEqual(queued, 3)
        finally:
            self._close_db(tmp)

    def test_disabled_reconcile_still_processes_due_queue(self):
        tmp = self._new_db()
        try:
            db.init_db()
            uid = 5005
            package_id = self._make_panel_package(uid)
            old_pid = self._seed_completed_payment(uid, package_id, quantity=2)
            db.setting_set("delivery_reconcile_enabled", "0")
            db.setting_set("delivery_reconcile_after_payment_id", str(old_pid))
            # Manually drop a pending queue row (simulates a queued retry).
            qid = db.enqueue_delivery_once(
                user_id=uid, chat_id=uid, package_id=package_id, payment_id=old_pid,
                slot_index=0, desired_name="manual", unit_price=500,
                payment_method="test", is_test=0,
            )
            calls = {"reconcile": 0, "delivered_qids": []}

            real_reconcile = delivery_worker._reconcile_completed_panel_payments

            def _spy_reconcile(*a, **kw):
                calls["reconcile"] += 1
                return real_reconcile(*a, **kw)

            from bot import db as _db_mod
            real_due = _db_mod.get_due_deliveries
            real_mark_delivered = _db_mod.mark_delivery_delivered

            def _fake_deliver_one(item):
                calls["delivered_qids"].append(item["id"])
                return True, "", 9999

            orig_deliver_one = delivery_worker._deliver_one
            orig_get_panel_id = delivery_worker._get_panel_id_for_package
            orig_notify_admin = delivery_worker._notify_admin
            delivery_worker._deliver_one = _fake_deliver_one
            delivery_worker._get_panel_id_for_package = lambda *_a, **_kw: None
            delivery_worker._notify_admin = lambda *_a, **_kw: None
            delivery_worker._reconcile_completed_panel_payments = _spy_reconcile
            try:
                delivery_worker._run_delivery_cycle()
            finally:
                delivery_worker._deliver_one = orig_deliver_one
                delivery_worker._get_panel_id_for_package = orig_get_panel_id
                delivery_worker._notify_admin = orig_notify_admin
                delivery_worker._reconcile_completed_panel_payments = real_reconcile
            self.assertEqual(calls["reconcile"], 0)
            self.assertIn(qid, calls["delivered_qids"])
        finally:
            self._close_db(tmp)

    def test_reset_delivery_cutoff_to_max_payment_id(self):
        tmp = self._new_db()
        try:
            db.init_db()
            uid = 6006
            package_id = self._make_panel_package(uid)
            pid = self._seed_completed_payment(uid, package_id, quantity=2)
            db.ensure_delivery_slots(pid, uid, package_id, 2)
            qid = db.enqueue_delivery_once(
                user_id=uid, chat_id=uid, package_id=package_id, payment_id=pid,
                slot_index=0, desired_name="x", unit_price=500,
                payment_method="test", is_test=0,
            )
            db.setting_set("delivery_reconcile_enabled", "0")
            db.setting_set("delivery_reconcile_after_payment_id", "0")
            result = db.reset_delivery_cutoff_to_max_payment_id()
            self.assertGreaterEqual(result["queue_cancelled"], 1)
            self.assertGreaterEqual(result["slots_cancelled"], 2)
            self.assertEqual(result["new_cutoff"], pid)
            self.assertEqual(db.setting_get("delivery_reconcile_enabled", ""), "1")
            self.assertEqual(
                db.setting_get("delivery_reconcile_after_payment_id", ""),
                str(pid),
            )
            with db.get_conn() as conn:
                pending = conn.execute(
                    "SELECT COUNT(*) AS c FROM delivery_queue WHERE status='pending'"
                ).fetchone()["c"]
            self.assertEqual(pending, 0)
        finally:
            self._close_db(tmp)


if __name__ == "__main__":
    unittest.main()
