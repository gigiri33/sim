# -*- coding: utf-8 -*-
"""
Background daemon that checks every 30 seconds whether each active panel
is reachable and updates its connection_status in the database.
"""
import logging
import threading
import time

log = logging.getLogger(__name__)

_INTERVAL = 30  # seconds between full check cycles


def _check_all_panels() -> None:
    """Run one health-check pass over all active panels."""
    from ..db import get_active_panels, update_panel_status
    from ..helpers import now_str
    from .client import PanelClient

    panels = get_active_panels()
    for panel in panels:
        client = PanelClient(
            protocol=panel["protocol"],
            host=panel["host"],
            port=panel["port"],
            path=panel["path"] or "",
            username=panel["username"],
            password=panel["password"],
        )
        ok, err = client.health_check()
        status = "connected" if ok else "disconnected"
        update_panel_status(panel["id"], status, err or "")
        log.debug("Panel %s → %s", panel["name"], status)


def _checker_loop() -> None:
    while True:
        try:
            _check_all_panels()
        except Exception as exc:
            log.error("Panel checker error: %s", exc)
        time.sleep(_INTERVAL)


def start_panel_checker() -> None:
    """Start the background panel health-checker thread (daemon)."""
    t = threading.Thread(target=_checker_loop, daemon=True, name="panel-checker")
    t.start()
