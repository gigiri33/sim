# -*- coding: utf-8 -*-
"""
ConfigFlow Worker API Server
Runs on the foreign (non-Iran) server alongside bot.py.
The Iran Worker polls this API to receive jobs and post results.

Run standalone:  python api.py
Or started automatically by bot.py when worker_api_enabled=
"""

import os
import json
import sqlite3
import functools
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv

load_dotenv()

try:
    from flask import Flask, request, jsonify
except ImportError:
    raise SystemExit("Flask is required: pip install flask")

DB_NAME  = os.getenv("DB_NAME", "configflow.db")
API_PORT = int(os.getenv("WORKER_API_PORT", "8080"))

app = Flask(__name__)


# ── DB helpers (read-only wrappers, separate connection per request) ───────────
_TZ_TEHRAN = timezone(timedelta(hours=3, minutes=30))

def _conn():
    c = sqlite3.connect(DB_NAME, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode = WAL")
    c.execute("PRAGMA busy_timeout = 5000")
    c.execute("PRAGMA foreign_keys = ON")
    return c

def _now():
    return datetime.now(_TZ_TEHRAN).strftime("%Y-%m-%d %H:%M:%S")


def _get_api_key():
    """Read API key live from DB (so changes take effect without restart)."""
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key='worker_api_key'").fetchone()
    return (row["value"] or "").strip() if row else ""


def _api_enabled():
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key='worker_api_enabled'").fetchone()
    return row and row["value"] == "1"


# ── Auth decorator ─────────────────────────────────────────────────────────────
def require_api_key(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not _api_enabled():
            return jsonify({"error": "API disabled"}), 503
        expected = _get_api_key()
        if not expected:
            return jsonify({"error": "API key not configured on server"}), 503
        provided = request.headers.get("X-API-Key", "")
        if provided != expected:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return wrapper


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "ConfigFlow Worker API"})


@app.route("/jobs/pending", methods=["GET"])
@require_api_key
def get_pending_jobs():
    """Return up to 20 pending/failed jobs with panel credentials."""
    with _conn() as c:
        rows = c.execute(
            "SELECT j.id, j.job_uuid, j.user_id, j.panel_id, j.panel_package_id,"
            " j.status, j.retry_count, j.created_at,"
            " p.ip, p.port, p.patch, p.username, p.password,"
            " pp.name AS pkg_name, pp.volume_gb, pp.duration_days, pp.inbound_id"
            " FROM xui_jobs j"
            " JOIN panels p  ON p.id=j.panel_id"
            " JOIN panel_packages pp ON pp.id=j.panel_package_id"
            " WHERE j.status IN ('pending','failed') AND j.retry_count < 5"
            "   AND p.is_active=1"
            " ORDER BY j.created_at ASC LIMIT 20"
        ).fetchall()
    jobs = [dict(r) for r in rows]
    return jsonify({"jobs": jobs})


@app.route("/jobs/<int:job_id>/start", methods=["POST"])
@require_api_key
def start_job(job_id):
    """Mark job as 'processing'."""
    with _conn() as c:
        row = c.execute("SELECT * FROM xui_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return jsonify({"error": "Job not found"}), 404
        if row["status"] not in ("pending", "failed"):
            return jsonify({"error": "Job not in actionable state", "status": row["status"]}), 409
        c.execute(
            "UPDATE xui_jobs SET status='processing', updated_at=? WHERE id=?",
            (_now(), job_id)
        )
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/jobs/<int:job_id>/result", methods=["POST"])
@require_api_key
def post_result(job_id):
    """Worker posts the generated config + link after successful 3x-ui client creation."""
    data = request.get_json(silent=True) or {}
    result_config = (data.get("result_config") or "").strip()
    result_link   = (data.get("result_link") or "").strip()
    if not result_config and not result_link:
        return jsonify({"error": "result_config or result_link required"}), 400

    with _conn() as c:
        row = c.execute("SELECT * FROM xui_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return jsonify({"error": "Job not found"}), 404
        c.execute(
            "UPDATE xui_jobs SET status='done', result_config=?, result_link=?,"
            " error_msg=NULL, updated_at=? WHERE id=?",
            (result_config, result_link, _now(), job_id)
        )
        user_id = row["user_id"]

    # Attempt to notify the user via bot (fire-and-forget, best effort)
    _notify_user_job_done(job_id, user_id, result_config, result_link)
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/jobs/<int:job_id>/error", methods=["POST"])
@require_api_key
def post_error(job_id):
    """Worker reports a failure so the job can be retried."""
    data = request.get_json(silent=True) or {}
    error_msg = (data.get("error") or "Unknown error")[:500]

    with _conn() as c:
        row = c.execute("SELECT * FROM xui_jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return jsonify({"error": "Job not found"}), 404
        new_retry = (row["retry_count"] or 0) + 1
        new_status = "failed" if new_retry < 5 else "error"
        c.execute(
            "UPDATE xui_jobs SET status=?, error_msg=?, retry_count=?, updated_at=?"
            " WHERE id=?",
            (new_status, error_msg, new_retry, _now(), job_id)
        )
    return jsonify({"ok": True, "job_id": job_id, "retry_count": new_retry})


@app.route("/jobs/<int:job_id>", methods=["GET"])
@require_api_key
def get_job(job_id):
    """Get job status (for polling from bot or worker)."""
    with _conn() as c:
        row = c.execute("SELECT * FROM xui_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(dict(row))


# ── Internal: Deliver config to Telegram user ─────────────────────────────────
def _notify_user_job_done(job_id, user_id, result_config, result_link):
    """Best-effort: send the config to the user via Telegram bot."""
    try:
        import telebot
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            return
        b = telebot.TeleBot(token, parse_mode="HTML")

        with _conn() as c:
            job = c.execute(
                "SELECT j.*, pp.name AS pkg_name, pp.volume_gb, pp.duration_days, p.name AS panel_name"
                " FROM xui_jobs j"
                " JOIN panel_packages pp ON pp.id=j.panel_package_id"
                " JOIN panels p ON p.id=j.panel_id"
                " WHERE j.id=?", (job_id,)
            ).fetchone()

        if not job:
            return

        import html as html_mod, io
        esc_fn = lambda t: html_mod.escape(str(t or ""))

        text = (
            "✅ <b>کانفیگ شما آماده است</b>\n\n"
            f"📦 Package: <b>{esc_fn(job['pkg_name'])}</b>\n"
            f"🖥 Panel: <b>{esc_fn(job['panel_name'])}</b>\n"
            f"🔋 Volume: <b>{job['volume_gb']} GB</b>\n"
            f"⏰ Duration: <b>{job['duration_days']} days</b>\n\n"
            f"🔗 Config:\n<code>{esc_fn(result_config)}</code>"
        )
        if result_link:
            text += f"\n\n🌐 Link: {esc_fn(result_link)}"

        import qrcode
        qr_img = qrcode.make(result_config or result_link)
        bio = io.BytesIO()
        qr_img.save(bio, format="PNG")
        bio.seek(0)
        bio.name = "qrcode.png"
        b.send_message(user_id, text, parse_mode="HTML")
        b.send_photo(user_id, bio)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Iran Agent / Panel endpoints
# ═══════════════════════════════════════════════════════════════════════════════
#
# Auth model:
#   Admin-level  → same X-API-Key header as existing worker endpoints
#   Agent-level  → X-Agent-UUID + X-Agent-Secret headers (verified via DB)
#
# All Iran endpoints are prefixed with /iran/
# ═══════════════════════════════════════════════════════════════════════════════

def _iran_services():
    """Lazy import to avoid circular imports at module load time."""
    from bot.iran_panel import services as svc
    return svc


def _iran_db():
    from bot.iran_panel import db as idb
    return idb


def _require_agent(f):
    """Decorator: authenticate Iran agent via X-Agent-UUID + X-Agent-Secret."""
    import functools

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not _api_enabled():
            return jsonify({"error": "API disabled"}), 503
        agent_uuid   = request.headers.get("X-Agent-UUID", "").strip()
        agent_secret = request.headers.get("X-Agent-Secret", "").strip()
        if not agent_uuid or not agent_secret:
            return jsonify({"error": "Missing X-Agent-UUID or X-Agent-Secret headers"}), 401
        svc   = _iran_services()
        agent = svc.authenticate_agent(agent_uuid, agent_secret)
        if not agent:
            return jsonify({"error": "Invalid or revoked agent credentials"}), 401
        # Attach to request context
        request._iran_agent = agent
        return f(*args, **kwargs)

    return wrapper


# ── Admin: create registration token ─────────────────────────────────────────

@app.route("/iran/tokens/create", methods=["POST"])
@require_api_key
def iran_create_token():
    """Admin creates a one-time registration token for a new Iran agent."""
    data      = request.get_json(silent=True) or {}
    label     = (data.get("label") or "").strip() or "unnamed"
    ttl_hours = int(data.get("ttl_hours") or 24)
    if ttl_hours < 1 or ttl_hours > 168:  # max 1 week
        return jsonify({"error": "ttl_hours must be 1–168"}), 400

    svc             = _iran_services()
    token, token_id = svc.make_registration_token(label, created_by=0, ttl_hours=ttl_hours)
    return jsonify({"ok": True, "token": token, "token_id": token_id, "ttl_hours": ttl_hours})


# ── Agent: register ────────────────────────────────────────────────────────────

@app.route("/iran/agents/register", methods=["POST"])
def iran_register_agent():
    """
    Iran-side agent calls this once with a registration token.
    Returns agent_uuid + agent_secret (store these on Iran side).
    """
    if not _api_enabled():
        return jsonify({"error": "API disabled"}), 503

    data = request.get_json(silent=True) or {}

    reg_token      = (data.get("registration_token") or "").strip()
    agent_name     = (data.get("agent_name") or "").strip()
    panel_name     = (data.get("panel_name") or "").strip()
    panel_host     = (data.get("panel_host") or "").strip()
    panel_port     = int(data.get("panel_port") or 2053)
    panel_path     = (data.get("panel_path") or "").strip()
    panel_username = (data.get("panel_username") or "").strip()
    panel_password = (data.get("panel_password") or "").strip()

    if not reg_token:
        return jsonify({"error": "registration_token is required"}), 400

    svc = _iran_services()
    try:
        result = svc.register_agent(
            reg_token=reg_token,
            agent_name=agent_name,
            panel_name=panel_name,
            panel_host=panel_host,
            panel_port=panel_port,
            panel_path=panel_path,
            panel_username=panel_username,
            panel_password=panel_password,
        )
    except svc.RegistrationError as exc:
        return jsonify({"error": str(exc)}), 422

    return jsonify({
        "ok":           True,
        "agent_uuid":   result["agent_uuid"],
        "agent_secret": result["agent_secret"],
        "panel_id":     result["panel_id"],
        "message":      "Registration successful. Store agent_uuid and agent_secret securely.",
    }), 201


# ── Agent: heartbeat ───────────────────────────────────────────────────────────

@app.route("/iran/agents/<agent_uuid>/heartbeat", methods=["POST"])
def iran_heartbeat(agent_uuid):
    if not _api_enabled():
        return jsonify({"error": "API disabled"}), 503

    agent_secret = request.headers.get("X-Agent-Secret", "").strip()
    if not agent_secret:
        return jsonify({"error": "X-Agent-Secret header required"}), 401

    svc = _iran_services()
    ok  = svc.process_heartbeat(agent_uuid, agent_secret)
    if not ok:
        return jsonify({"error": "Invalid or revoked agent credentials"}), 401

    return jsonify({"ok": True, "timestamp": _now()})


# ── Agent: report panel test result ───────────────────────────────────────────

@app.route("/iran/agents/<agent_uuid>/panel-test", methods=["POST"])
def iran_panel_test_result(agent_uuid):
    """Iran agent reports whether a 3x-ui panel login test succeeded."""
    if not _api_enabled():
        return jsonify({"error": "API disabled"}), 503

    agent_secret = request.headers.get("X-Agent-Secret", "").strip()
    if not agent_secret:
        return jsonify({"error": "X-Agent-Secret header required"}), 401

    data     = request.get_json(silent=True) or {}
    panel_id = data.get("panel_id")
    success  = bool(data.get("success", False))
    message  = (data.get("message") or "")[:500]

    if panel_id is None:
        return jsonify({"error": "panel_id is required"}), 400

    svc = _iran_services()
    ok  = svc.record_panel_test(agent_uuid, agent_secret, int(panel_id), success, message)
    if not ok:
        return jsonify({"error": "Auth failed or panel not found"}), 401

    return jsonify({"ok": True})


# ── Agent: fetch panels ────────────────────────────────────────────────────────

@app.route("/iran/agents/<agent_uuid>/panels", methods=["GET"])
def iran_get_agent_panels(agent_uuid):
    """Iran agent fetches the panels assigned to it (with decrypted credentials)."""
    if not _api_enabled():
        return jsonify({"error": "API disabled"}), 503

    agent_secret = request.headers.get("X-Agent-Secret", "").strip()
    if not agent_secret:
        return jsonify({"error": "X-Agent-Secret header required"}), 401

    svc    = _iran_services()
    panels = svc.list_panels_for_agent_response(agent_uuid, agent_secret)
    if panels is None:
        return jsonify({"error": "Invalid or revoked agent credentials"}), 401

    return jsonify({"ok": True, "panels": panels})


# ── Admin: list panels ─────────────────────────────────────────────────────────

@app.route("/iran/panels", methods=["GET"])
@require_api_key
def iran_list_panels():
    idb  = _iran_db()
    rows = idb.get_all_iran_panels()
    # Strip encrypted password from response
    for r in rows:
        r.pop("password_enc", None)
    return jsonify({"ok": True, "panels": rows})


# ── Admin: list agents ─────────────────────────────────────────────────────────

@app.route("/iran/agents", methods=["GET"])
@require_api_key
def iran_list_agents():
    idb  = _iran_db()
    rows = idb.get_all_iran_agents()
    # Strip secret hashes from response
    for r in rows:
        r.pop("secret_hash", None)
        r.pop("secret_salt", None)
    return jsonify({"ok": True, "agents": rows})


# ── Admin: toggle panel ────────────────────────────────────────────────────────

@app.route("/iran/panels/<int:panel_id>/toggle", methods=["POST"])
@require_api_key
def iran_toggle_panel(panel_id):
    data      = request.get_json(silent=True) or {}
    is_active = int(bool(data.get("is_active", True)))
    idb       = _iran_db()
    panel     = idb.get_iran_panel(panel_id)
    if not panel:
        return jsonify({"error": "Panel not found"}), 404
    idb.toggle_iran_panel(panel_id, is_active)
    return jsonify({"ok": True, "panel_id": panel_id, "is_active": is_active})


# ── Admin: delete panel ────────────────────────────────────────────────────────

@app.route("/iran/panels/<int:panel_id>", methods=["DELETE"])
@require_api_key
def iran_delete_panel(panel_id):
    idb   = _iran_db()
    panel = idb.get_iran_panel(panel_id)
    if not panel:
        return jsonify({"error": "Panel not found"}), 404
    idb.delete_iran_panel(panel_id)
    return jsonify({"ok": True})


# ── Admin: revoke / delete agent ──────────────────────────────────────────────

@app.route("/iran/agents/<int:agent_id>/revoke", methods=["POST"])
@require_api_key
def iran_revoke_agent(agent_id):
    idb   = _iran_db()
    agent = idb.get_iran_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    idb.revoke_iran_agent(agent_id)
    return jsonify({"ok": True})


@app.route("/iran/agents/<int:agent_id>", methods=["DELETE"])
@require_api_key
def iran_delete_agent(agent_id):
    idb   = _iran_db()
    agent = idb.get_iran_agent(agent_id)
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    idb.delete_iran_agent(agent_id)
    return jsonify({"ok": True})


# ── Admin: panel status / logs ─────────────────────────────────────────────────

@app.route("/iran/panels/<int:panel_id>", methods=["GET"])
@require_api_key
def iran_get_panel(panel_id):
    idb   = _iran_db()
    panel = idb.get_iran_panel(panel_id)
    if not panel:
        return jsonify({"error": "Panel not found"}), 404
    panel.pop("password_enc", None)
    return jsonify({"ok": True, "panel": panel})


@app.route("/iran/panels/<int:panel_id>/logs", methods=["GET"])
@require_api_key
def iran_panel_logs(panel_id):
    idb  = _iran_db()
    logs = idb.get_panel_logs(panel_id, limit=50)
    return jsonify({"ok": True, "logs": logs})


if __name__ == "__main__":
    print(f"✅ ConfigFlow Worker API starting on port {API_PORT}...")
    app.run(host="0.0.0.0", port=API_PORT, use_reloader=False)
