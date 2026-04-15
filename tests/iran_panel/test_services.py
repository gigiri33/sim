"""
Unit tests for bot/iran_panel/services.py — using in-memory SQLite.
"""
import sys
import os
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ── Patch DB connection before importing services ─────────────
import sqlite3
import threading

_local = threading.local()

def _get_test_conn():
    if not hasattr(_local, "conn"):
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _local.conn = conn
    return _local.conn

# Patch get_conn used in db and services modules
with patch("bot.iran_panel.db.get_conn", side_effect=_get_test_conn):
    from bot.iran_panel import db as idb
    idb.init_iran_panel_tables.__globals__["get_conn"] = _get_test_conn
    idb.init_iran_panel_tables()

# Monkey-patch get_conn in idb module
idb.get_conn = _get_test_conn

import bot.iran_panel.services as svc
svc.idb.get_conn = _get_test_conn  # type: ignore[attr-defined]

# Also patch config
with patch.dict(os.environ, {"BOT_TOKEN": "test-token-xyz", "DB_NAME": ":memory:"}):
    pass

os.environ.setdefault("BOT_TOKEN", "test-token-xyz")


class TestMakeRegistrationToken(unittest.TestCase):
    def setUp(self):
        idb.init_iran_panel_tables()

    def test_creates_token(self):
        token, token_id = svc.make_registration_token("test-label", 999)
        self.assertTrue(len(token) > 0)
        self.assertIsInstance(token_id, int)

    def test_token_in_db(self):
        token, token_id = svc.make_registration_token("label2", 1)
        row = idb.get_reg_token(token)
        self.assertIsNotNone(row)
        self.assertEqual(row["label"], "label2")
        self.assertEqual(row["is_used"], 0)


class TestRegisterAgent(unittest.TestCase):
    def setUp(self):
        idb.init_iran_panel_tables()

    def _make_token(self, label="t1"):
        return svc.make_registration_token(label, 999)

    def test_successful_registration(self):
        token, _ = self._make_token()
        result = svc.register_agent(
            reg_token    = token,
            agent_name   = "TestAgent",
            panel_name   = "TestPanel",
            panel_host   = "1.2.3.4",
            panel_port   = 2053,
            panel_path   = "",
            panel_user   = "admin",
            panel_pass   = "secret",
        )
        self.assertIn("agent_uuid", result)
        self.assertIn("agent_secret", result)
        self.assertIn("panel_id", result)

    def test_token_consumed_after_registration(self):
        token, _ = self._make_token("t2")
        svc.register_agent(
            reg_token  = token, agent_name="A1", panel_name="P1",
            panel_host = "1.2.3.4", panel_port=2053, panel_path="",
            panel_user = "u", panel_pass="p",
        )
        row = idb.get_reg_token(token)
        self.assertEqual(row["is_used"], 1)

    def test_duplicate_registration_raises(self):
        token, _ = self._make_token("t3")
        svc.register_agent(
            reg_token  = token, agent_name="A2", panel_name="P2",
            panel_host = "5.6.7.8", panel_port=2053, panel_path="",
            panel_user = "u", panel_pass="p",
        )
        with self.assertRaises(svc.RegistrationError):
            svc.register_agent(
                reg_token  = token, agent_name="A3", panel_name="P3",
                panel_host = "9.10.11.12", panel_port=2053, panel_path="",
                panel_user = "u", panel_pass="p",
            )

    def test_expired_token_raises(self):
        token, tid = self._make_token("t4")
        # manually expire it
        with _get_test_conn() as conn:
            conn.execute(
                "UPDATE iran_reg_tokens SET expires_at=? WHERE id=?",
                ((datetime.utcnow() - timedelta(hours=1)).isoformat(), tid)
            )
        with self.assertRaises(svc.RegistrationError):
            svc.register_agent(
                reg_token  = token, agent_name="A4", panel_name="P4",
                panel_host = "1.1.1.1", panel_port=2053, panel_path="",
                panel_user = "u", panel_pass="p",
            )


class TestAuthenticateAndHeartbeat(unittest.TestCase):
    def setUp(self):
        idb.init_iran_panel_tables()
        token, _ = svc.make_registration_token("auth-test", 999)
        result = svc.register_agent(
            reg_token  = token, agent_name="AuthAgent", panel_name="AP",
            panel_host = "2.2.2.2", panel_port=2053, panel_path="",
            panel_user = "admin", panel_pass="pass",
        )
        self._uuid   = result["agent_uuid"]
        self._secret = result["agent_secret"]

    def test_valid_auth(self):
        agent = svc.authenticate_agent(self._uuid, self._secret)
        self.assertIsNotNone(agent)

    def test_wrong_secret(self):
        agent = svc.authenticate_agent(self._uuid, "wrongsecret")
        self.assertIsNone(agent)

    def test_wrong_uuid(self):
        agent = svc.authenticate_agent("00000000-0000-0000-0000-000000000000", self._secret)
        self.assertIsNone(agent)

    def test_heartbeat_returns_true(self):
        ok = svc.process_heartbeat(self._uuid, self._secret)
        self.assertTrue(ok)

    def test_heartbeat_wrong_creds(self):
        ok = svc.process_heartbeat(self._uuid, "badsecret")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
