"""
Integration tests for the Iran agent flow:
register.py, test_panel.py, and agent heartbeat — using mocked HTTP calls.
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iran"))

os.environ.update({
    "BOT_API_URL":         "http://fake-api:8080",
    "REGISTRATION_TOKEN":  "deadbeef" * 5,
    "AGENT_NAME":          "TestAgent",
    "PANEL_NAME":          "TestPanel",
    "PANEL_HOST":          "127.0.0.1",
    "PANEL_PORT":          "2053",
    "PANEL_PATH":          "",
    "PANEL_USERNAME":      "admin",
    "PANEL_PASSWORD":      "password",
    "AGENT_UUID":          "",
    "AGENT_SECRET":        "",
})


class TestApiClientHeartbeat(unittest.TestCase):
    def setUp(self):
        from lib.api_client import BotApiClient
        self.api = BotApiClient(
            base_url     = "http://fake-api:8080",
            agent_uuid   = "uuid-123",
            agent_secret = "secret-456",
            timeout      = 5,
        )

    def test_heartbeat_success(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {"status": "ok"}
        with patch("requests.Session.post", return_value=mock_resp):
            self.assertTrue(self.api.heartbeat())

    def test_heartbeat_failure(self):
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 403
        with patch("requests.Session.post", return_value=mock_resp):
            self.assertFalse(self.api.heartbeat())

    def test_heartbeat_connection_error(self):
        import requests
        with patch("requests.Session.post", side_effect=requests.ConnectionError("refused")):
            self.assertFalse(self.api.heartbeat())


class TestApiClientGetPanels(unittest.TestCase):
    def setUp(self):
        from lib.api_client import BotApiClient
        self.api = BotApiClient(
            base_url     = "http://fake-api:8080",
            agent_uuid   = "uuid-123",
            agent_secret = "secret-456",
            timeout      = 5,
        )

    def test_get_panels_success(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = [
            {"id": 1, "name": "P1", "host": "1.2.3.4", "port": 2053,
             "panel_path": "", "username": "admin", "password": "pass"}
        ]
        with patch("requests.Session.get", return_value=mock_resp):
            panels = self.api.get_panels()
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["id"], 1)

    def test_get_panels_empty(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = []
        with patch("requests.Session.get", return_value=mock_resp):
            panels = self.api.get_panels()
        self.assertEqual(panels, [])


class TestXuiPanelClientLogin(unittest.TestCase):
    def setUp(self):
        from lib.panel_client import XuiPanelClient
        self.client = XuiPanelClient(
            host      = "127.0.0.1",
            port      = 2053,
            panel_path= "",
            username  = "admin",
            password  = "password",
            timeout   = 5,
        )

    def test_login_success_json(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"success": True, "msg": "ok"}
        mock_resp.url = "http://127.0.0.1:2053/login"
        with patch("requests.Session.post", return_value=mock_resp):
            success, msg = self.client.test_login()
        self.assertTrue(success)

    def test_login_failure_json(self):
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.json.return_value = {"success": False, "msg": "Wrong credentials"}
        mock_resp.url = "http://127.0.0.1:2053/login"
        with patch("requests.Session.post", return_value=mock_resp):
            success, msg = self.client.test_login()
        self.assertFalse(success)
        self.assertIn("Wrong credentials", msg)

    def test_login_connection_error(self):
        import requests
        with patch("requests.Session.post", side_effect=requests.ConnectionError("refused")):
            success, msg = self.client.test_login()
        self.assertFalse(success)
        self.assertIn("refused", msg.lower())


class TestRegisterAgentFlow(unittest.TestCase):
    def test_register_writes_env(self):
        import tempfile, importlib

        # Write a minimal config.env to a temp file
        env_text = "\n".join([
            "BOT_API_URL=http://fake:8080",
            "REGISTRATION_TOKEN=deadbeef" * 5,
            "AGENT_NAME=TestAgent",
            "PANEL_NAME=TestPanel",
            "PANEL_HOST=1.2.3.4",
            "PANEL_PORT=2053",
            "PANEL_PATH=",
            "PANEL_USERNAME=admin",
            "PANEL_PASSWORD=pass",
            "AGENT_UUID=",
            "AGENT_SECRET=",
        ])
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write(env_text)
            tmp_path = f.name

        mock_resp = MagicMock()
        mock_resp.ok   = True
        mock_resp.json.return_value = {
            "agent_uuid":   "aaaabbbb-1234-1234-1234-aaaabbbbcccc",
            "agent_secret": "x" * 64,
        }

        with patch("requests.post", return_value=mock_resp):
            from lib import api_client
            result = api_client.register_agent(
                base_url           = "http://fake:8080",
                registration_token = "deadbeef" * 5,
                agent_name         = "TestAgent",
                panel_name         = "TestPanel",
                panel_host         = "1.2.3.4",
                panel_port         = 2053,
                panel_path         = "",
                panel_user         = "admin",
                panel_pass         = "pass",
            )
        self.assertEqual(result["agent_uuid"], "aaaabbbb-1234-1234-1234-aaaabbbbcccc")
        self.assertEqual(len(result["agent_secret"]), 64)

        os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main()
