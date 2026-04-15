#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build a Xray config JSON from a parsed VLESS info dict.

Creates:
  - Inbound: HTTP proxy on 127.0.0.1:10809  (used by the Iran Agent)
  - Outbound: VLESS to the foreign server
  - Routing: all traffic via the VLESS outbound

Usage:
    from build_xray_config import build_config
    cfg_json = build_config(vless_info, local_port=10809)

    # or as a CLI tool:
    python build_xray_config.py '{"uuid":"...","address":"...","port":443,...}' > config.json
"""
from __future__ import annotations

import json
import sys
from typing import Any


def build_config(info: dict, local_port: int = 10809) -> dict:
    """
    Build a complete Xray JSON config dict.

    Args:
        info: dict returned by parse_vless.parse_vless()
        local_port: local HTTP proxy port for the inbound (default 10809)

    Returns:
        dict that can be serialised to config.json for xray-core
    """
    # ── Inbound — local HTTP proxy ─────────────────────────────────────────────
    inbound = {
        "tag":      "http-in",
        "listen":   "127.0.0.1",
        "port":     local_port,
        "protocol": "http",
        "settings": {
            "allowTransparent": False,
            "timeout":          300,
        },
        "sniffing": {
            "enabled":      True,
            "destOverride": ["http", "tls"],
        },
    }

    # ── Stream settings ────────────────────────────────────────────────────────
    net_type     = info.get("type", "tcp")
    security     = info.get("security", "none")
    stream: dict = {"network": net_type}

    # Transport-specific settings
    if net_type == "ws":
        stream["wsSettings"] = {
            "path":    info.get("path", "/"),
            "headers": {"Host": info.get("host", info.get("address", ""))},
        }
    elif net_type == "grpc":
        stream["grpcSettings"] = {
            "serviceName": info.get("service_name", ""),
            "multiMode":   False,
        }
    elif net_type == "h2":
        stream["httpSettings"] = {
            "path": info.get("path", "/"),
            "host": [info.get("host", info.get("address", ""))],
        }
    elif net_type == "tcp" and info.get("header_type") == "http":
        stream["tcpSettings"] = {
            "header": {"type": "http"},
        }

    # TLS settings
    if security == "tls":
        tls_cfg: dict[str, Any] = {
            "serverName":    info.get("sni") or info.get("address", ""),
            "allowInsecure": False,
        }
        if info.get("alpn"):
            tls_cfg["alpn"] = info["alpn"]
        if info.get("fp"):
            tls_cfg["fingerprint"] = info["fp"]
        stream["tlsSettings"] = tls_cfg
        stream["security"]    = "tls"

    # Reality settings
    elif security == "reality":
        stream["realitySettings"] = {
            "serverName":  info.get("sni") or info.get("host") or info.get("address", ""),
            "fingerprint": info.get("fp", "chrome"),
            "publicKey":   info.get("pbk", ""),
            "shortId":     info.get("sid", ""),
            "spiderX":     info.get("spx", ""),
        }
        stream["security"] = "reality"

    # ── Outbound — VLESS ───────────────────────────────────────────────────────
    vless_user: dict[str, Any] = {
        "id":           info["uuid"],
        "encryption":   info.get("encryption", "none"),
    }
    if info.get("flow"):
        vless_user["flow"] = info["flow"]

    outbound = {
        "tag":      "vless-out",
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": info["address"],
                    "port":    info["port"],
                    "users":   [vless_user],
                }
            ]
        },
        "streamSettings": stream,
    }

    # ── Direct outbound (fallback / DNS) ───────────────────────────────────────
    direct_out = {"tag": "direct", "protocol": "freedom"}
    block_out  = {"tag": "block",  "protocol": "blackhole"}

    # ── Routing ────────────────────────────────────────────────────────────────
    routing = {
        "domainStrategy": "IPIfNonMatch",
        "rules": [
            # Block ads / malware (optional, keeps config minimal)
            # Route everything else via the VLESS outbound
            {
                "type":        "field",
                "inboundTag":  ["http-in"],
                "outboundTag": "vless-out",
            },
        ],
    }

    # ── DNS ────────────────────────────────────────────────────────────────────
    dns = {
        "servers": ["8.8.8.8", "1.1.1.1"],
    }

    return {
        "log": {
            "loglevel": "warning",
        },
        "dns":       dns,
        "inbounds":  [inbound],
        "outbounds": [outbound, direct_out, block_out],
        "routing":   routing,
    }


def main() -> None:
    """CLI: read JSON from argv[1] or stdin, print config JSON to stdout."""
    if len(sys.argv) >= 2:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"ERROR: invalid JSON input: {exc}", file=sys.stderr)
        sys.exit(1)

    local_port = int(sys.argv[2]) if len(sys.argv) >= 3 else 10809

    cfg = build_config(info, local_port=local_port)
    print(json.dumps(cfg, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
