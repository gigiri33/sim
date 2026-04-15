#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse a VLESS URI into a structured dictionary.

Supported URI format:
    vless://UUID@host:port?params#fragment

Supported query parameters:
    encryption, security, type, host, sni, path, serviceName,
    flow, fp, pbk, sid, spx, alpn, headerType, seed, quicSecurity,
    key, mode, authority

Supported transport types: tcp, ws, grpc, h2, quic
Supported security: none, tls, reality

Usage:
    from parse_vless import parse_vless
    info = parse_vless("vless://uuid@1.2.3.4:443?security=reality&...")
"""
from __future__ import annotations

import urllib.parse


class VlessParseError(ValueError):
    """Raised when a VLESS URI is invalid or unsupported."""


def parse_vless(uri: str) -> dict:
    """
    Parse a VLESS URI string and return a dict with all extracted fields.

    Returns a dict with keys:
        uuid, address, port, encryption, security, type,
        host, sni, path, service_name, flow, fp, pbk, sid, spx,
        alpn, header_type, name

    Raises VlessParseError on any parse failure.
    """
    uri = uri.strip()
    if not uri.startswith("vless://"):
        raise VlessParseError(f"URI must start with 'vless://', got: {uri[:20]!r}")

    # urllib cannot parse vless:// scheme natively; rewrite as http:// for parsing
    try:
        parsed = urllib.parse.urlparse(uri.replace("vless://", "http://", 1))
    except Exception as exc:
        raise VlessParseError(f"Failed to parse URI: {exc}") from exc

    # ── UUID (userinfo part) ───────────────────────────────────────────────────
    uuid = parsed.username
    if not uuid:
        raise VlessParseError("UUID is missing from the URI (expected vless://UUID@host:port)")
    uuid = urllib.parse.unquote(uuid)

    # ── Address & port ─────────────────────────────────────────────────────────
    address = parsed.hostname
    if not address:
        raise VlessParseError("Host address is missing from the URI")

    port = parsed.port
    if port is None:
        raise VlessParseError("Port is missing from the URI")
    if not (1 <= port <= 65535):
        raise VlessParseError(f"Port {port} is out of range (1–65535)")

    # ── Query parameters ───────────────────────────────────────────────────────
    qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)

    def _q(key: str, default: str = "") -> str:
        vals = qs.get(key)
        return urllib.parse.unquote(vals[0]) if vals else default

    encryption   = _q("encryption", "none")
    security     = _q("security",   "none")
    net_type     = _q("type",       "tcp")
    host         = _q("host")          # SNI override / WebSocket host header
    sni          = _q("sni")           # TLS/Reality SNI
    path         = _q("path",   "/")   # WS path / HTTP/2 path
    service_name = _q("serviceName")   # gRPC service name
    flow         = _q("flow")          # e.g. xtls-rprx-vision
    fp           = _q("fp")            # TLS fingerprint (chrome, firefox, …)
    pbk          = _q("pbk")           # Reality public key
    sid          = _q("sid")           # Reality short ID
    spx          = _q("spx")           # Reality spider X
    alpn_raw     = _q("alpn")          # comma-separated ALPN list
    header_type  = _q("headerType")    # TCP header type (http / none)
    name         = urllib.parse.unquote(parsed.fragment) if parsed.fragment else ""

    # Validate security value
    valid_security = {"none", "tls", "reality"}
    if security and security not in valid_security:
        raise VlessParseError(
            f"Unsupported security value: {security!r}. "
            f"Expected one of: {', '.join(sorted(valid_security))}"
        )

    # Validate transport type
    valid_types = {"tcp", "ws", "grpc", "h2", "quic", "kcp", "mkcp"}
    if net_type and net_type not in valid_types:
        raise VlessParseError(
            f"Unsupported transport type: {net_type!r}. "
            f"Expected one of: {', '.join(sorted(valid_types))}"
        )

    # Reality requires pbk and sid
    if security == "reality":
        if not pbk:
            raise VlessParseError("Reality security requires 'pbk' (public key) parameter")
        if not sid:
            raise VlessParseError("Reality security requires 'sid' (short ID) parameter")

    alpn: list[str] = [a.strip() for a in alpn_raw.split(",") if a.strip()] if alpn_raw else []

    return {
        "uuid":         uuid,
        "address":      address,
        "port":         port,
        "encryption":   encryption,
        "security":     security,
        "type":         net_type,
        "host":         host,
        "sni":          sni or host,      # fall back to host for SNI
        "path":         path,
        "service_name": service_name,
        "flow":         flow,
        "fp":           fp,
        "pbk":          pbk,
        "sid":          sid,
        "spx":          spx,
        "alpn":         alpn,
        "header_type":  header_type,
        "name":         name,
    }
