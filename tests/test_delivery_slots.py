# -*- coding: utf-8 -*-
"""
Reproducible bulk panel delivery slot tests.

Run from project root:
    python -m unittest tests.test_delivery_slots
"""
import os
import tempfile
import threading
import unittest

os.environ.setdefault("BOT_TOKEN", "123456:TESTTOKEN")
os.environ.setdefault("ADMIN_IDS", "1")

from bot import config as bot_config
from bot import db
from bot.ui import notifications
from bot.handlers import callbacks


class DeliverySlotBulkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(prefix="delivery-slots-", suffix=".db", delete=False)
        self.tmp.close()
        bot_config.DB_NAME = self.tmp.name
        db.DB_NAME = self.tmp.name
        old_conn = getattr(db._tls, "conn", None)
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                pass
            db._tls.conn = None
        db.init_db()
        self.uid = 1001
        self.package_id = self._make_panel_package()
        self.sent = []
        self._orig_create = callbacks._create_panel_config
        self._orig_deliver = callbacks._deliver_panel_config_to_user
        self._orig_sleep = callbacks.time.sleep
        self._orig_notify_panel_error = callbacks._notify_panel_error
        self._orig_admin_purchase_notify = notifications.admin_purchase_notify
        self._orig_referral_reward = notifications.check_and_give_referral_purchase_reward
        callbacks._deliver_panel_config_to_user = lambda chat_id, pc_id, pkg: self.sent.append((chat_id, pc_id))
        callbacks.time.sleep = lambda *_a, **_kw: None
        callbacks._notify_panel_error = lambda *a, **kw: None
        notifications.admin_purchase_notify = lambda *a, **kw: None
        notifications.check_and_give_referral_purchase_reward = lambda *a, **kw: None

    def tearDown(self):
        callbacks._create_panel_config = self._orig_create
        callbacks._deliver_panel_config_to_user = self._orig_deliver
        callbacks.time.sleep = self._orig_sleep
        callbacks._notify_panel_error = self._orig_notify_panel_error
        notifications.admin_purchase_notify = self._orig_admin_purchase_notify
        notifications.check_and_give_referral_purchase_reward = self._orig_referral_reward
        old_conn = getattr(db._tls, "conn", None)
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                pass
            db._tls.conn = None
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _make_panel_package(self):
        with db.get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO users(user_id,full_name,username,balance,joined_at,last_seen_at) "
                "VALUES(?,?,?,?,?,?)",
                (self.uid, "Test User", "test", 0, db.now_str(), db.now_str()),
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

    def _create_payment(self, quantity, service_names=None):
        payment_id = db.create_payment(
            "config_purchase", self.uid, self.package_id, 1000 * quantity,
            "test", status="completed", quantity=quantity,
        )
        if service_names:
            db.set_payment_service_names(payment_id, service_names)
        return payment_id

    def _fake_success_factory(self, prefix="cfg"):
        def _fake_create(uid, package_id, payment_id, chat_id=None, desired_name=None, is_test=0, slot_index=None):
            pc_id = db.add_panel_config(
                user_id=uid,
                package_id=package_id,
                panel_id=1,
                panel_type="sanaei",
                inbound_id=1,
                inbound_port=443,
                client_name=desired_name or f"{prefix}-{slot_index}",
                client_uuid=f"uuid-{payment_id}-{slot_index}",
                client_sub_url="",
                client_config_text=f"vless://uuid-{payment_id}-{slot_index}@example.com:443#{desired_name or slot_index}",
                expire_at=None,
                payment_id=payment_id,
                inbound_protocol="vless",
                delivery_slot_index=slot_index,
            )
            return True, "config_only", pc_id, desired_name or f"{prefix}-{slot_index}"
        return _fake_create

    def _counts(self, payment_id):
        with db.get_conn() as conn:
            panel_configs = conn.execute(
                "SELECT COUNT(*) AS c FROM panel_configs WHERE payment_id=?", (payment_id,)
            ).fetchone()["c"]
            queue_rows = conn.execute(
                "SELECT COUNT(*) AS c FROM delivery_queue WHERE payment_id=? AND status='pending'", (payment_id,)
            ).fetchone()["c"]
        slots = db.count_delivery_slots(payment_id)
        return panel_configs, queue_rows, slots

    def test_quantity_10_all_success_delivers_10_slots(self):
        payment_id = self._create_payment(10)
        callbacks._create_panel_config = self._fake_success_factory()

        purchase_ids, pending_ids = callbacks._deliver_bulk_configs(
            self.uid, self.uid, self.package_id, 10000, "test", 10, payment_id
        )

        panel_configs, queue_rows, slots = self._counts(payment_id)
        self.assertEqual(len(purchase_ids), 10)
        self.assertEqual(pending_ids, [])
        self.assertEqual(panel_configs, 10)
        self.assertEqual(queue_rows, 0)
        self.assertEqual(slots["delivered"], 10)
        self.assertEqual(len(self.sent), 10)

    def test_quantity_10_first_success_rest_queued(self):
        payment_id = self._create_payment(10)

        def _fake_create(uid, package_id, payment_id, chat_id=None, desired_name=None, is_test=0, slot_index=None):
            if slot_index == 0:
                return self._fake_success_factory()(uid, package_id, payment_id, chat_id, desired_name, is_test, slot_index)
            return False, "panel down", None, None

        callbacks._create_panel_config = _fake_create
        purchase_ids, pending_ids = callbacks._deliver_bulk_configs(
            self.uid, self.uid, self.package_id, 10000, "test", 10, payment_id
        )

        panel_configs, queue_rows, slots = self._counts(payment_id)
        self.assertEqual(len(purchase_ids), 1)
        self.assertEqual(len(pending_ids), 9)
        self.assertEqual(panel_configs, 1)
        self.assertEqual(queue_rows, 9)
        self.assertEqual(slots["delivered"], 1)
        self.assertEqual(slots["queued"], 9)

        callbacks._deliver_bulk_configs(self.uid, self.uid, self.package_id, 10000, "test", 10, payment_id)
        panel_configs2, queue_rows2, slots2 = self._counts(payment_id)
        self.assertEqual(panel_configs2, 1)
        self.assertEqual(queue_rows2, 9)
        self.assertEqual(slots2["delivered"], 1)
        self.assertEqual(slots2["queued"], 9)

    def test_quantity_10_concurrent_processing_caps_at_10_configs(self):
        payment_id = self._create_payment(10)
        callbacks._create_panel_config = self._fake_success_factory("concurrent")
        results = []

        def _run():
            results.append(callbacks._deliver_bulk_configs(
                self.uid, self.uid, self.package_id, 10000, "test", 10, payment_id
            ))

        threads = [threading.Thread(target=_run), threading.Thread(target=_run)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        panel_configs, queue_rows, slots = self._counts(payment_id)
        self.assertEqual(panel_configs, 10)
        self.assertEqual(queue_rows, 0)
        self.assertEqual(slots["delivered"], 10)
        self.assertLessEqual(len(self.sent), 10)

    def test_quantity_15_service_names_are_slot_ordered(self):
        names = [f"svc-{i:02d}" for i in range(15)]
        payment_id = self._create_payment(15, names)
        callbacks._create_panel_config = self._fake_success_factory("named")

        callbacks._deliver_bulk_configs(
            self.uid, self.uid, self.package_id, 15000, "test", 15, payment_id,
            service_names=names,
        )

        with db.get_conn() as conn:
            rows = conn.execute(
                "SELECT delivery_slot_index, client_name FROM panel_configs "
                "WHERE payment_id=? ORDER BY delivery_slot_index ASC",
                (payment_id,),
            ).fetchall()
        self.assertEqual(len(rows), 15)
        self.assertEqual([r["client_name"] for r in rows], names)
        self.assertEqual(db.count_delivery_slots(payment_id)["delivered"], 15)


if __name__ == "__main__":
    unittest.main()
