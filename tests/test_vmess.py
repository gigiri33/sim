# -*- coding: utf-8 -*-
"""
VMess encode/decode/patch validation script.

Run from the project root:
    python tests/test_vmess.py

No external dependencies — only stdlib.
The helpers are inlined here so the script runs independently of bot deps.
"""
import sys
import base64
import json
import uuid as _uuid_mod


# ── Inline the helpers from bot/panels/client.py for standalone testing ────────

def is_vmess_link(text) -> bool:
    return isinstance(text, str) and text.strip().startswith("vmess://")


def decode_vmess_link(vmess_url: str) -> dict:
    if not is_vmess_link(vmess_url):
        raise ValueError("Not a vmess:// link")
    b64 = vmess_url.strip()[8:].split("#")[0]
    b64 += "=" * (-len(b64) % 4)
    try:
        decoded = base64.b64decode(b64).decode("utf-8")
    except Exception as exc:
        raise ValueError(f"VMess base64 decode error: {exc}") from exc
    try:
        obj = json.loads(decoded)
    except Exception as exc:
        raise ValueError(f"VMess JSON parse error: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("VMess payload is not a JSON object")
    return obj


def encode_vmess_link(obj: dict) -> str:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    return "vmess://" + base64.b64encode(raw.encode("utf-8")).decode()


def patch_vmess_link(vmess_url: str, new_uuid: str, new_name: str) -> str:
    obj = decode_vmess_link(vmess_url)
    obj["id"] = new_uuid
    obj["ps"] = new_name
    return encode_vmess_link(obj)


def validate_vmess_link(vmess_url: str) -> tuple:
    if not is_vmess_link(vmess_url):
        return False, "Not a vmess:// link"
    try:
        obj = decode_vmess_link(vmess_url)
    except ValueError as exc:
        return False, str(exc)
    uid = obj.get("id", "")
    try:
        _uuid_mod.UUID(str(uid))
    except Exception:
        return False, f"Invalid UUID in VMess id field: {uid!r}"
    if not (obj.get("ps") or "").strip():
        return False, "VMess ps (name) field is empty"
    if "add" in obj and not str(obj["add"]).strip():
        return False, "VMess add (host) field is empty"
    try:
        re_encoded = encode_vmess_link(obj)
        decode_vmess_link(re_encoded)
    except Exception as exc:
        return False, f"VMess round-trip encode/decode failed: {exc}"
    return True, None


# ── Test fixtures ──────────────────────────────────────────────────────────────

SAMPLE_VMESS = (
    "vmess://"
    + base64.b64encode(
        json.dumps({
            "v": "2",
            "ps": "my-server-original",
            "add": "cdn.example.com",
            "port": "443",
            "id": "11111111-2222-3333-4444-555555555555",
            "aid": 0,
            "net": "ws",
            "type": "none",
            "host": "cdn.example.com",
            "path": "/ws",
            "tls": "tls",
            "sni": "cdn.example.com",
            "fp": "chrome",
            "scy": "auto",
        }, ensure_ascii=False).encode()
    ).decode()
)

NEW_UUID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
NEW_NAME = "my-new-service"

TESTS_PASSED = 0
TESTS_FAILED = 0


def check(label: str, condition: bool, detail: str = ""):
    global TESTS_PASSED, TESTS_FAILED
    if condition:
        print(f"  \u2705 PASS: {label}")
        TESTS_PASSED += 1
    else:
        print(f"  \u274c FAIL: {label}" + (f" \u2014 {detail}" if detail else ""))
        TESTS_FAILED += 1


print("\n=== VMess helper unit tests ===\n")

# ── 1. is_vmess_link ──────────────────────────────────────────────────────────
print("1. is_vmess_link")
check("valid vmess link detected", is_vmess_link(SAMPLE_VMESS))
check("vless:// not detected as vmess", not is_vmess_link("vless://abc@host:443"))
check("empty string not vmess", not is_vmess_link(""))
check("None not vmess", not is_vmess_link(None))  # type: ignore

# ── 2. decode_vmess_link ───────────────────────────────────────────────────────
print("\n2. decode_vmess_link")
obj = decode_vmess_link(SAMPLE_VMESS)
check("decode returns dict", isinstance(obj, dict))
check("id field present", "id" in obj)
check("id matches original", obj["id"] == "11111111-2222-3333-4444-555555555555")
check("ps matches original", obj["ps"] == "my-server-original")
check("add preserved", obj["add"] == "cdn.example.com")
check("port preserved", obj["port"] == "443")
check("net preserved", obj["net"] == "ws")
check("path preserved", obj["path"] == "/ws")
check("tls preserved", obj["tls"] == "tls")
check("aid preserved", obj["aid"] == 0)

try:
    decode_vmess_link("vless://notvalid")
    check("bad scheme raises ValueError", False, "no exception raised")
except ValueError:
    check("bad scheme raises ValueError", True)

try:
    decode_vmess_link("vmess://!!!invalid-base64!!!")
    check("invalid base64 raises ValueError", False, "no exception raised")
except ValueError:
    check("invalid base64 raises ValueError", True)

# ── 3. encode_vmess_link ───────────────────────────────────────────────────────
print("\n3. encode_vmess_link round-trip")
re_encoded = encode_vmess_link(obj)
check("re-encoded starts with vmess://", re_encoded.startswith("vmess://"))
re_decoded = decode_vmess_link(re_encoded)
check("round-trip id unchanged", re_decoded["id"] == obj["id"])
check("round-trip add unchanged", re_decoded["add"] == obj["add"])
check("round-trip net unchanged", re_decoded["net"] == obj["net"])

# ── 4. patch_vmess_link ────────────────────────────────────────────────────────
print("\n4. patch_vmess_link \u2014 only id and ps change")
patched = patch_vmess_link(SAMPLE_VMESS, NEW_UUID, NEW_NAME)
pobj = decode_vmess_link(patched)
check("patched id == new UUID", pobj["id"] == NEW_UUID)
check("patched ps == new name", pobj["ps"] == NEW_NAME)
check("add unchanged after patch", pobj["add"] == "cdn.example.com")
check("port unchanged after patch", pobj["port"] == "443")
check("net unchanged after patch", pobj["net"] == "ws")
check("path unchanged after patch", pobj["path"] == "/ws")
check("tls unchanged after patch", pobj["tls"] == "tls")
check("sni unchanged after patch", pobj.get("sni") == "cdn.example.com")
check("fp unchanged after patch", pobj.get("fp") == "chrome")
check("aid unchanged after patch", pobj.get("aid") == 0)

# ── 5. validate_vmess_link ─────────────────────────────────────────────────────
print("\n5. validate_vmess_link")
valid, err = validate_vmess_link(patched)
check("patched vmess validates OK", valid, err or "")

valid2, _ = validate_vmess_link(SAMPLE_VMESS)
check("original vmess validates OK", valid2)

# Invalid UUID
bad_uuid_obj = dict(obj)
bad_uuid_obj["id"] = "not-a-uuid"
bad_enc = "vmess://" + base64.b64encode(json.dumps(bad_uuid_obj).encode()).decode()
v3, e3 = validate_vmess_link(bad_enc)
check("invalid UUID fails validation", not v3, e3 or "")

# Empty ps
bad_ps_obj = dict(obj)
bad_ps_obj["ps"] = ""
bad_ps_enc = "vmess://" + base64.b64encode(json.dumps(bad_ps_obj).encode()).decode()
v4, e4 = validate_vmess_link(bad_ps_enc)
check("empty ps fails validation", not v4, e4 or "")

# Not a vmess link
v5, e5 = validate_vmess_link("vless://abc@host:443")
check("vless:// fails vmess validation", not v5, e5 or "")

# ── 6. VLESS existing behavior unaffected ────────────────────────────────────
print("\n6. VLESS config \u2014 patch_vmess_link raises ValueError (correct)")
try:
    patch_vmess_link("vless://uuid@host:443?type=tcp#name", NEW_UUID, NEW_NAME)
    check("vless input raises ValueError", False, "no exception raised")
except ValueError:
    check("vless input raises ValueError", True)

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n=== Results: {TESTS_PASSED} passed, {TESTS_FAILED} failed ===\n")
if TESTS_FAILED > 0:
    sys.exit(1)


# ── Realistic VMess sample using WebSocket+TLS ─────────────────────────────────
SAMPLE_VMESS = (
    "vmess://"
    + __import__("base64").b64encode(
        __import__("json").dumps({
            "v": "2",
            "ps": "my-server-original",
            "add": "cdn.example.com",
            "port": "443",
            "id": "11111111-2222-3333-4444-555555555555",
            "aid": 0,
            "net": "ws",
            "type": "none",
            "host": "cdn.example.com",
            "path": "/ws",
            "tls": "tls",
            "sni": "cdn.example.com",
            "fp": "chrome",
            "scy": "auto",
        }, ensure_ascii=False).encode()
    ).decode()
)

NEW_UUID = "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
NEW_NAME = "my-new-service"

TESTS_PASSED = 0
TESTS_FAILED = 0


def check(label: str, condition: bool, detail: str = ""):
    global TESTS_PASSED, TESTS_FAILED
    if condition:
        print(f"  ✅ PASS: {label}")
        TESTS_PASSED += 1
    else:
        print(f"  ❌ FAIL: {label}" + (f" — {detail}" if detail else ""))
        TESTS_FAILED += 1


print("\n=== VMess helper unit tests ===\n")

# ── 1. is_vmess_link ──────────────────────────────────────────────────────────
print("1. is_vmess_link")
check("valid vmess link detected", is_vmess_link(SAMPLE_VMESS))
check("vless:// not detected as vmess", not is_vmess_link("vless://abc@host:443"))
check("empty string not vmess", not is_vmess_link(""))
check("None not vmess", not is_vmess_link(None))  # type: ignore

# ── 2. decode_vmess_link ───────────────────────────────────────────────────────
print("\n2. decode_vmess_link")
obj = decode_vmess_link(SAMPLE_VMESS)
check("decode returns dict", isinstance(obj, dict))
check("id field present", "id" in obj)
check("id matches original", obj["id"] == "11111111-2222-3333-4444-555555555555")
check("ps matches original", obj["ps"] == "my-server-original")
check("add preserved", obj["add"] == "cdn.example.com")
check("port preserved", obj["port"] == "443")
check("net preserved", obj["net"] == "ws")
check("path preserved", obj["path"] == "/ws")
check("tls preserved", obj["tls"] == "tls")
check("aid preserved", obj["aid"] == 0)

try:
    decode_vmess_link("vless://notvalid")
    check("bad scheme raises ValueError", False, "no exception raised")
except ValueError:
    check("bad scheme raises ValueError", True)

try:
    decode_vmess_link("vmess://!!!invalid-base64!!!")
    check("invalid base64 raises ValueError", False, "no exception raised")
except ValueError:
    check("invalid base64 raises ValueError", True)

# ── 3. encode_vmess_link ───────────────────────────────────────────────────────
print("\n3. encode_vmess_link round-trip")
re_encoded = encode_vmess_link(obj)
check("re-encoded starts with vmess://", re_encoded.startswith("vmess://"))
re_decoded = decode_vmess_link(re_encoded)
check("round-trip id unchanged", re_decoded["id"] == obj["id"])
check("round-trip add unchanged", re_decoded["add"] == obj["add"])
check("round-trip net unchanged", re_decoded["net"] == obj["net"])

# ── 4. patch_vmess_link ────────────────────────────────────────────────────────
print("\n4. patch_vmess_link — only id and ps change")
patched = patch_vmess_link(SAMPLE_VMESS, NEW_UUID, NEW_NAME)
pobj = decode_vmess_link(patched)
check("patched id == new UUID", pobj["id"] == NEW_UUID)
check("patched ps == new name", pobj["ps"] == NEW_NAME)
check("add unchanged after patch", pobj["add"] == "cdn.example.com")
check("port unchanged after patch", pobj["port"] == "443")
check("net unchanged after patch", pobj["net"] == "ws")
check("path unchanged after patch", pobj["path"] == "/ws")
check("tls unchanged after patch", pobj["tls"] == "tls")
check("sni unchanged after patch", pobj.get("sni") == "cdn.example.com")
check("fp unchanged after patch", pobj.get("fp") == "chrome")
check("aid unchanged after patch", pobj.get("aid") == 0)

# ── 5. validate_vmess_link ─────────────────────────────────────────────────────
print("\n5. validate_vmess_link")
valid, err = validate_vmess_link(patched)
check("patched vmess validates OK", valid, err)

valid2, _ = validate_vmess_link(SAMPLE_VMESS)
check("original vmess validates OK", valid2)

# Invalid UUID
import json, base64
bad_uuid_obj = dict(obj)
bad_uuid_obj["id"] = "not-a-uuid"
bad_enc = "vmess://" + base64.b64encode(json.dumps(bad_uuid_obj).encode()).decode()
v3, e3 = validate_vmess_link(bad_enc)
check("invalid UUID fails validation", not v3, e3)

# Empty ps
bad_ps_obj = dict(obj)
bad_ps_obj["ps"] = ""
bad_ps_enc = "vmess://" + base64.b64encode(json.dumps(bad_ps_obj).encode()).decode()
v4, e4 = validate_vmess_link(bad_ps_enc)
check("empty ps fails validation", not v4, e4)

# Not a vmess link
v5, e5 = validate_vmess_link("vless://abc@host:443")
check("vless:// fails vmess validation", not v5, e5)

# ── 6. VLESS existing behavior unaffected ────────────────────────────────────
print("\n6. VLESS config — patch_vmess_link raises ValueError (correct)")
try:
    patch_vmess_link("vless://uuid@host:443?type=tcp#name", NEW_UUID, NEW_NAME)
    check("vless input raises ValueError", False, "no exception raised")
except ValueError:
    check("vless input raises ValueError", True)

# ── Summary ────────────────────────────────────────────────────────────────────
print(f"\n=== Results: {TESTS_PASSED} passed, {TESTS_FAILED} failed ===\n")
if TESTS_FAILED > 0:
    sys.exit(1)
