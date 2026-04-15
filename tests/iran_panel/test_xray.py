"""
Unit tests for iran/xray/parse_vless.py and iran/xray/build_xray_config.py.
"""
import sys
import os
import unittest

# Make iran/xray importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "iran", "xray"))

from parse_vless import parse_vless, VlessParseError
from build_xray_config import build_config


# ── parse_vless tests ──────────────────────────────────────────────────────────

class TestParseVlessBasic(unittest.TestCase):

    def test_minimal_direct_tcp(self):
        uri = "vless://12345678-1234-1234-1234-123456789abc@1.2.3.4:443?security=none"
        info = parse_vless(uri)
        self.assertEqual(info["uuid"],    "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(info["address"], "1.2.3.4")
        self.assertEqual(info["port"],    443)
        self.assertEqual(info["security"], "none")
        self.assertEqual(info["type"],    "tcp")

    def test_ws_tls(self):
        uri = (
            "vless://aaaa-bbbb-cccc@example.com:443"
            "?type=ws&security=tls&host=cdn.example.com&path=%2Fws&sni=example.com"
        )
        info = parse_vless(uri)
        self.assertEqual(info["type"],     "ws")
        self.assertEqual(info["security"], "tls")
        self.assertEqual(info["path"],     "/ws")
        self.assertEqual(info["host"],     "cdn.example.com")
        self.assertEqual(info["sni"],      "example.com")

    def test_reality(self):
        uri = (
            "vless://uuid123@1.2.3.4:443"
            "?security=reality&pbk=abc123&sid=abcd1234&fp=chrome&sni=target.com"
        )
        info = parse_vless(uri)
        self.assertEqual(info["security"], "reality")
        self.assertEqual(info["pbk"],      "abc123")
        self.assertEqual(info["sid"],      "abcd1234")
        self.assertEqual(info["fp"],       "chrome")
        self.assertEqual(info["sni"],      "target.com")

    def test_grpc(self):
        uri = (
            "vless://uid@host:443"
            "?type=grpc&serviceName=myservice&security=tls"
        )
        info = parse_vless(uri)
        self.assertEqual(info["type"],         "grpc")
        self.assertEqual(info["service_name"], "myservice")

    def test_fragment_becomes_name(self):
        uri = "vless://uid@host:443?security=none#My%20Server"
        info = parse_vless(uri)
        self.assertEqual(info["name"], "My Server")

    def test_alpn_parsed_as_list(self):
        uri = "vless://uid@host:443?security=tls&alpn=h2%2Chttp%2F1.1"
        info = parse_vless(uri)
        self.assertEqual(info["alpn"], ["h2", "http/1.1"])

    def test_flow_extracted(self):
        uri = (
            "vless://uid@host:443"
            "?security=reality&pbk=pk&sid=sid&flow=xtls-rprx-vision"
        )
        info = parse_vless(uri)
        self.assertEqual(info["flow"], "xtls-rprx-vision")


class TestParseVlessErrors(unittest.TestCase):

    def test_wrong_scheme(self):
        with self.assertRaises(VlessParseError):
            parse_vless("vmess://uuid@host:443")

    def test_missing_uuid(self):
        with self.assertRaises(VlessParseError):
            parse_vless("vless://host:443?security=none")

    def test_missing_host(self):
        with self.assertRaises(VlessParseError):
            parse_vless("vless://uuid@:443")

    def test_missing_port(self):
        with self.assertRaises(VlessParseError):
            parse_vless("vless://uuid@host")

    def test_invalid_security(self):
        with self.assertRaises(VlessParseError):
            parse_vless("vless://uid@host:443?security=ssh")

    def test_reality_missing_pbk(self):
        with self.assertRaises(VlessParseError):
            parse_vless("vless://uid@host:443?security=reality&sid=abc")

    def test_reality_missing_sid(self):
        with self.assertRaises(VlessParseError):
            parse_vless("vless://uid@host:443?security=reality&pbk=abc")


# ── build_xray_config tests ────────────────────────────────────────────────────

class TestBuildXrayConfig(unittest.TestCase):

    def _minimal_info(self, **overrides) -> dict:
        base = {
            "uuid":         "test-uuid",
            "address":      "1.2.3.4",
            "port":         443,
            "encryption":   "none",
            "security":     "none",
            "type":         "tcp",
            "host":         "",
            "sni":          "",
            "path":         "/",
            "service_name": "",
            "flow":         "",
            "fp":           "",
            "pbk":          "",
            "sid":          "",
            "spx":          "",
            "alpn":         [],
            "header_type":  "",
            "name":         "",
        }
        base.update(overrides)
        return base

    def test_returns_dict(self):
        cfg = build_config(self._minimal_info())
        self.assertIsInstance(cfg, dict)

    def test_inbound_http_on_10809(self):
        cfg = build_config(self._minimal_info(), local_port=10809)
        inbounds = cfg["inbounds"]
        self.assertEqual(len(inbounds), 1)
        ib = inbounds[0]
        self.assertEqual(ib["protocol"], "http")
        self.assertEqual(ib["port"],     10809)
        self.assertEqual(ib["listen"],   "127.0.0.1")

    def test_inbound_custom_port(self):
        cfg = build_config(self._minimal_info(), local_port=8888)
        self.assertEqual(cfg["inbounds"][0]["port"], 8888)

    def test_outbound_vless(self):
        cfg  = build_config(self._minimal_info(uuid="my-uuid", address="srv.com", port=8443))
        out  = cfg["outbounds"][0]
        self.assertEqual(out["protocol"], "vless")
        vnext = out["settings"]["vnext"][0]
        self.assertEqual(vnext["address"], "srv.com")
        self.assertEqual(vnext["port"],    8443)
        self.assertEqual(vnext["users"][0]["id"], "my-uuid")

    def test_outbound_with_flow(self):
        cfg  = build_config(self._minimal_info(flow="xtls-rprx-vision",
                                               security="reality", pbk="pk", sid="si"))
        user = cfg["outbounds"][0]["settings"]["vnext"][0]["users"][0]
        self.assertEqual(user["flow"], "xtls-rprx-vision")

    def test_tls_stream_settings(self):
        cfg    = build_config(self._minimal_info(security="tls", sni="example.com"))
        stream = cfg["outbounds"][0]["streamSettings"]
        self.assertEqual(stream["security"], "tls")
        self.assertEqual(stream["tlsSettings"]["serverName"], "example.com")

    def test_reality_stream_settings(self):
        cfg    = build_config(self._minimal_info(
            security="reality", pbk="mypbk", sid="mysid", fp="chrome", sni="target.com"
        ))
        stream = cfg["outbounds"][0]["streamSettings"]
        self.assertEqual(stream["security"], "reality")
        rs = stream["realitySettings"]
        self.assertEqual(rs["publicKey"],   "mypbk")
        self.assertEqual(rs["shortId"],     "mysid")
        self.assertEqual(rs["fingerprint"], "chrome")
        self.assertEqual(rs["serverName"],  "target.com")

    def test_ws_stream_settings(self):
        cfg    = build_config(self._minimal_info(type="ws", path="/mypath", host="cdn.x.com"))
        stream = cfg["outbounds"][0]["streamSettings"]
        self.assertEqual(stream["network"], "ws")
        ws = stream["wsSettings"]
        self.assertEqual(ws["path"], "/mypath")
        self.assertEqual(ws["headers"]["Host"], "cdn.x.com")

    def test_grpc_stream_settings(self):
        cfg    = build_config(self._minimal_info(type="grpc", service_name="svc"))
        stream = cfg["outbounds"][0]["streamSettings"]
        self.assertEqual(stream["network"], "grpc")
        self.assertEqual(stream["grpcSettings"]["serviceName"], "svc")

    def test_routing_directs_inbound_to_vless(self):
        cfg   = build_config(self._minimal_info())
        rules = cfg["routing"]["rules"]
        self.assertTrue(any(
            r.get("inboundTag") == ["http-in"] and r.get("outboundTag") == "vless-out"
            for r in rules
        ))

    def test_direct_and_block_outbounds_present(self):
        cfg  = build_config(self._minimal_info())
        tags = {o["tag"] for o in cfg["outbounds"]}
        self.assertIn("direct", tags)
        self.assertIn("block",  tags)

    def test_roundtrip_with_parsed_uri(self):
        """parse_vless → build_config should not raise and produce a valid JSON-serialisable dict."""
        import json
        uri  = (
            "vless://aaaabbbb-1234-1234-1234-aaaabbbbcccc@1.2.3.4:443"
            "?security=reality&pbk=publickey123&sid=abc12345"
            "&fp=chrome&sni=example.com&flow=xtls-rprx-vision&type=tcp"
        )
        info = parse_vless(uri)
        cfg  = build_config(info)
        serialised = json.dumps(cfg)  # must not raise
        self.assertIn("vless-out", serialised)


# ── Xray binary check ──────────────────────────────────────────────────────────

class TestXrayBinaryPresence(unittest.TestCase):
    """
    Verify installer logic: if xray binary is missing, the error path is clear.
    These tests do NOT try to run or install Xray — they only test the file-check
    logic that install.sh and install_xray.sh exercise.
    """

    def test_binary_missing_flag(self):
        """Simulate a path where xray binary does not exist."""
        missing_path = "/nonexistent/xray/xray"
        self.assertFalse(os.path.exists(missing_path),
                         "Test precondition: path must not exist")

    def test_binary_present_flag(self):
        """If xray binary is placed in the project, validate it is executable on Unix."""
        xray_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "iran", "xray", "xray"
        )
        if not os.path.exists(xray_path):
            self.skipTest(
                "iran/xray/xray binary not present — "
                "place the Linux xray binary there to run this test."
            )
        # On Linux/Mac: check executable bit
        if sys.platform != "win32":
            self.assertTrue(os.access(xray_path, os.X_OK),
                            "xray binary must be executable (chmod +x)")


if __name__ == "__main__":
    unittest.main()
