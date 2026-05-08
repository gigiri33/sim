# -*- coding: utf-8 -*-
"""
Deprecated. Not imported. Do not use for panel config delivery.

The old delivery_queue / delivery_slots / completed-payment reconcile system was
removed from active runtime because it could replay historical payments and send
duplicate panel configs after deploy/restart. Historical database tables remain
for compatibility only.
"""
