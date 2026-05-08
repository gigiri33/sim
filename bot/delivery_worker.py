# -*- coding: utf-8 -*-
"""
Deprecated. Not imported at startup. Do not use for panel config delivery.

The old panel delivery queue/reconcile worker caused duplicate delivery after
updates/restarts by replaying historical queue rows and completed payments.
Panel config delivery is now handled exclusively by bot.direct_delivery.

This module remains as a safe compatibility shim for old imports/tests. Runtime
settings such as delivery_queue_system_enabled and delivery_reconcile_enabled do
not reactivate anything here.
"""

import logging

log = logging.getLogger(__name__)


def _run_delivery_cycle():
    """No-op compatibility hook. Legacy queue processing is permanently disabled."""
    log.info("[DeliveryWorker] deprecated no-op; direct_delivery is the only panel delivery path")
    return None


def start_delivery_worker():
    """No-op compatibility hook. Startup must not launch legacy queue worker."""
    log.info("[DeliveryWorker] not started; legacy panel delivery queue is disabled")
    return None
