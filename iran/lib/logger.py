# -*- coding: utf-8 -*-
"""
Structured logging for the Iran agent.

Usage:
    from lib.logger import get_logger
    log = get_logger(__name__)
    log.info("Agent started")
    log.error("Login failed: %s", msg)

Secrets are never passed to this module — callers must sanitize.
"""
import logging
import os
import sys


def get_logger(name: str = "agent") -> logging.Logger:
    """Return a configured logger. Safe to call multiple times."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level      = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler (optional)
    log_file = os.getenv("LOG_FILE", "").strip()
    if log_file:
        try:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(fmt)
            logger.addHandler(fh)
        except OSError as exc:
            logger.warning("Cannot open log file %s: %s", log_file, exc)

    return logger
