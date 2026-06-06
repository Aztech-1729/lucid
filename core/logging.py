"""
Structured logging setup using structlog.

Configures async-safe context propagation via contextvars,
ISO timestamps, and JSON or console rendering based on settings.
"""

from __future__ import annotations

import logging
import sys

import structlog


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """
    Configure structlog for the application.

    Args:
        log_level: Standard logging level name (DEBUG, INFO, WARNING, ERROR).
        log_format: "json" for production, "console" for local development.
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Shared processors for both json and console output
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if log_format == "console":
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(),
        )
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a bound logger, optionally with a component name pre-bound."""
    log = structlog.get_logger()
    if name:
        log = log.bind(component=name)
    return log
