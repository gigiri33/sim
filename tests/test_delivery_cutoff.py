# -*- coding: utf-8 -*-
"""
Compatibility tests for the deprecated delivery queue/cutoff helpers.

The old reconcile/queue system must remain disabled and must never enqueue or
process panel delivery from completed payments.
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
        db.init_db()
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


class DeprecatedDeliveryQueueTests(_TempDBMixin, unittest.TestCase):
    def test_completed_payment_reconcile_query_is_permanently_disabled(self):
        tmp = self._new_db()
        try:
            uid = 1001
            package_id = self._make_panel_package(uid)
            pid = self._seed_completed_payment(uid, package_id, quantity=3)

            rows = db.get_completed_panel_payments_for_delivery_reconcile(after_payment_id=0)
            self.assertEqual(rows, [])

            delivery_worker._run_delivery_cycle()
            with db.get_conn() as conn:
                queued = conn.execute(
                    "SELECT COUNT(*) AS c FROM delivery_queue WHERE payment_id=?",
                    (pid,),
                ).fetchone()["c"]
                configs = conn.execute(
                    "SELECT COUNT(*) AS c FROM panel_configs WHERE payment_id=?",
                    (pid,),
                ).fetchone()["c"]
            self.assertEqual(queued, 0)
            self.assertEqual(configs, 0)
        finally:
            self._close_db(tmp)

    def test_enqueue_helpers_are_noops(self):
        tmp = self._new_db()
        try:
            uid = 2002
            package_id = self._make_panel_package(uid)
            pid = self._seed_completed_payment(uid, package_id, quantity=1)

            qid = db.enqueue_delivery_once(
                user_id=uid, chat_id=uid, package_id=package_id, payment_id=pid,
                slot_index=0, desired_name="x", unit_price=1000,
                payment_method="test", is_test=0,
            )
            self.assertIsNone(qid)
            self.assertEqual(db.get_due_deliveries(), [])
            with db.get_conn() as conn:
                queued = conn.execute("SELECT COUNT(*) AS c FROM delivery_queue").fetchone()["c"]
            self.assertEqual(queued, 0)
        finally:
            self._close_db(tmp)

    def test_reset_marks_old_rows_disabled_and_keeps_reconcile_off(self):
        tmp = self._new_db()
        try:
            uid = 3003
            package_id = self._make_panel_package(uid)
            pid = self._seed_completed_payment(uid, package_id, quantity=2)
            db.ensure_delivery_slots(pid, uid, package_id, 2)
            with db.get_conn() as conn:
                conn.execute(
                    "INSERT INTO delivery_queue(user_id,chat_id,package_id,payment_id,status,created_at,next_retry_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (uid, uid, package_id, pid, "pending", db.now_str(), db.now_str()),
                )
            db.setting_set("delivery_reconcile_enabled", "1")

            result = db.reset_delivery_cutoff_to_max_payment_id()
            self.assertGreaterEqual(result["queue_cancelled"], 1)
            self.assertGreaterEqual(result["slots_cancelled"], 2)
            self.assertEqual(db.setting_get("delivery_reconcile_enabled", ""), "0")

            with db.get_conn() as conn:
                active_queue = conn.execute(
                    "SELECT COUNT(*) AS c FROM delivery_queue WHERE status IN ('pending','retry','processing','creating','queued','failed')"
                ).fetchone()["c"]
                active_slots = conn.execute(
                    "SELECT COUNT(*) AS c FROM delivery_slots WHERE status IN ('pending','retry','processing','creating','queued','failed')"
                ).fetchone()["c"]
            self.assertEqual(active_queue, 0)
            self.assertEqual(active_slots, 0)
        finally:
            self._close_db(tmp)

    def test_worker_start_is_noop(self):
        self.assertIsNone(delivery_worker.start_delivery_worker())
        self.assertIsNone(delivery_worker._run_delivery_cycle())


if __name__ == "__main__":
    unittest.main()
