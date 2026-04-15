# -*- coding: utf-8 -*-
"""
DB layer for Iran Panel management.

Tables (migrated idempotently via init_iran_panel_tables()):
  iran_reg_tokens  – one-time registration tokens created by admin
  iran_agents      – registered Iran-side agents
  iran_panels      – 3x-ui panel configs reported by each agent
  iran_panel_logs  – status/check history per panel
"""
from __future__ import annotations

from ..db import get_conn
from ..helpers import now_str


# ── Migration ──────────────────────────────────────────────────────────────────

def init_iran_panel_tables() -> None:
    """Create or upgrade Iran-panel tables in the bot's own DB. Idempotent."""
    with get_conn() as conn:
        conn.executescript("""
            -- One-time registration tokens (admin creates, agent consumes once)
            CREATE TABLE IF NOT EXISTS iran_reg_tokens (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token       TEXT    NOT NULL UNIQUE,
                label       TEXT    NOT NULL DEFAULT '',
                expires_at  TEXT    NOT NULL,
                is_used     INTEGER NOT NULL DEFAULT 0,
                used_by_uuid TEXT,
                created_by  INTEGER NOT NULL,
                created_at  TEXT    NOT NULL
            );

            -- Registered Iran-side agents
            CREATE TABLE IF NOT EXISTS iran_agents (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_uuid       TEXT    NOT NULL UNIQUE,
                name             TEXT    NOT NULL,
                secret_hash      TEXT    NOT NULL,
                secret_salt      TEXT    NOT NULL,
                status           TEXT    NOT NULL DEFAULT 'pending',
                last_seen_at     TEXT,
                last_error       TEXT,
                registered_at    TEXT,
                created_at       TEXT    NOT NULL,
                updated_at       TEXT    NOT NULL
            );

            -- 3x-ui panels registered by agents
            CREATE TABLE IF NOT EXISTS iran_panels (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id        INTEGER NOT NULL,
                name            TEXT    NOT NULL,
                host            TEXT    NOT NULL,
                port            INTEGER NOT NULL DEFAULT 2053,
                panel_path      TEXT    NOT NULL DEFAULT '',
                username        TEXT    NOT NULL,
                password_enc    TEXT    NOT NULL,
                is_active       INTEGER NOT NULL DEFAULT 1,
                status          TEXT    NOT NULL DEFAULT 'pending',
                last_check_at   TEXT,
                last_seen_at    TEXT,
                last_error      TEXT,
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL,
                FOREIGN KEY(agent_id) REFERENCES iran_agents(id) ON DELETE CASCADE
            );

            -- Panel check/status log
            CREATE TABLE IF NOT EXISTS iran_panel_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                panel_id    INTEGER NOT NULL,
                status      TEXT    NOT NULL,
                message     TEXT,
                created_at  TEXT    NOT NULL,
                FOREIGN KEY(panel_id) REFERENCES iran_panels(id) ON DELETE CASCADE
            );
        """)

        # Add columns that may be missing in older installs (safe ALTER TABLE)
        _safe_add_columns(conn)


def _safe_add_columns(conn) -> None:
    """Add new columns to existing tables without failing if they already exist."""
    _alterations = [
        ("iran_agents",  "last_error TEXT"),
        ("iran_agents",  "registered_at TEXT"),
        ("iran_panels",  "last_error TEXT"),
        ("iran_panels",  "last_seen_at TEXT"),
        ("iran_panels",  "last_check_at TEXT"),
    ]
    for table, col_def in _alterations:
        col_name = col_def.split()[0]
        existing = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if col_name not in existing:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
            except Exception:
                pass  # already exists (race with another thread)


# ── Registration Tokens ────────────────────────────────────────────────────────

def create_reg_token(token: str, label: str, expires_at: str, created_by: int) -> int:
    """Insert a new registration token. Returns row id."""
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO iran_reg_tokens(token, label, expires_at, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (token, label, expires_at, created_by, now_str()),
        )
        return cur.lastrowid


def consume_reg_token(token: str, agent_uuid: str) -> dict | None:
    """
    Atomically mark token as used if it is valid (not used, not expired).
    Returns the token row on success, None on failure.
    """
    now = now_str()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM iran_reg_tokens "
            "WHERE token=? AND is_used=0 AND expires_at > ?",
            (token, now),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE iran_reg_tokens SET is_used=1, used_by_uuid=? WHERE id=?",
            (agent_uuid, row["id"]),
        )
    return dict(row)


def get_reg_tokens(include_expired: bool = False) -> list[dict]:
    """List registration tokens. By default only unused/non-expired."""
    now = now_str()
    with get_conn() as conn:
        if include_expired:
            rows = conn.execute(
                "SELECT * FROM iran_reg_tokens ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM iran_reg_tokens "
                "WHERE is_used=0 AND expires_at > ? ORDER BY created_at DESC",
                (now,),
            ).fetchall()
    return [dict(r) for r in rows]


def delete_reg_token(token_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM iran_reg_tokens WHERE id=?", (token_id,))


# ── Iran Agents ────────────────────────────────────────────────────────────────

def create_iran_agent(
    agent_uuid: str,
    name: str,
    secret_hash: str,
    secret_salt: str,
) -> int:
    """Insert a new agent record. Returns row id."""
    now = now_str()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO iran_agents"
            "(agent_uuid, name, secret_hash, secret_salt, status,"
            " registered_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?, ?)",
            (agent_uuid, name, secret_hash, secret_salt, now, now, now),
        )
        return cur.lastrowid


def get_iran_agent_by_uuid(agent_uuid: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM iran_agents WHERE agent_uuid=?", (agent_uuid,)
        ).fetchone()
    return dict(row) if row else None


def get_iran_agent(agent_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM iran_agents WHERE id=?", (agent_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_iran_agents() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM iran_agents ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_agent_heartbeat(agent_uuid: str) -> None:
    now = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE iran_agents SET last_seen_at=?, updated_at=? WHERE agent_uuid=?",
            (now, now, agent_uuid),
        )


def update_agent_status(agent_id: int, status: str, error: str | None = None) -> None:
    now = now_str()
    with get_conn() as conn:
        conn.execute(
            "UPDATE iran_agents SET status=?, last_error=?, updated_at=? WHERE id=?",
            (status, error, now, agent_id),
        )


def revoke_iran_agent(agent_id: int) -> None:
    update_agent_status(agent_id, "revoked")


def delete_iran_agent(agent_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM iran_agents WHERE id=?", (agent_id,))


# ── Iran Panels ────────────────────────────────────────────────────────────────

def create_iran_panel(
    agent_id: int,
    name: str,
    host: str,
    port: int,
    panel_path: str,
    username: str,
    password_enc: str,
) -> int:
    """Insert a new panel record. Returns row id."""
    now = now_str()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO iran_panels"
            "(agent_id, name, host, port, panel_path, username, password_enc,"
            " is_active, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'pending', ?, ?)",
            (agent_id, name, host, port, panel_path, username, password_enc, now, now),
        )
        return cur.lastrowid


def get_iran_panel(panel_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT p.*, a.name AS agent_name, a.agent_uuid, a.status AS agent_status, "
            "a.last_seen_at AS agent_last_seen "
            "FROM iran_panels p "
            "JOIN iran_agents a ON a.id = p.agent_id "
            "WHERE p.id=?",
            (panel_id,),
        ).fetchone()
    return dict(row) if row else None


def get_all_iran_panels() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT p.*, a.name AS agent_name, a.agent_uuid, a.status AS agent_status, "
            "a.last_seen_at AS agent_last_seen "
            "FROM iran_panels p "
            "JOIN iran_agents a ON a.id = p.agent_id "
            "ORDER BY p.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_panels_for_agent(agent_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM iran_panels WHERE agent_id=? ORDER BY created_at ASC",
            (agent_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_iran_panel_status(
    panel_id: int,
    status: str,
    error: str | None = None,
    check_type: str = "test",
) -> None:
    """Update panel status after a test/heartbeat. Logs the event."""
    now = now_str()
    with get_conn() as conn:
        if check_type == "heartbeat":
            conn.execute(
                "UPDATE iran_panels SET status=?, last_seen_at=?, last_error=?, updated_at=? "
                "WHERE id=?",
                (status, now, error, now, panel_id),
            )
        else:
            conn.execute(
                "UPDATE iran_panels SET status=?, last_check_at=?, last_error=?, updated_at=? "
                "WHERE id=?",
                (status, now, error, now, panel_id),
            )
        conn.execute(
            "INSERT INTO iran_panel_logs(panel_id, status, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            (panel_id, status, error or "", now),
        )


def toggle_iran_panel(panel_id: int, is_active: int) -> None:
    now = now_str()
    status = "disabled" if not is_active else "pending"
    with get_conn() as conn:
        conn.execute(
            "UPDATE iran_panels SET is_active=?, status=?, updated_at=? WHERE id=?",
            (is_active, status, now, panel_id),
        )


def delete_iran_panel(panel_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM iran_panels WHERE id=?", (panel_id,))


# ── Panel Logs ─────────────────────────────────────────────────────────────────

def get_panel_logs(panel_id: int, limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM iran_panel_logs WHERE panel_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (panel_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]
