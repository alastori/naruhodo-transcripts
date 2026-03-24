"""Logging configuration with progress tracking and ETA."""

import logging
import sys
import time
from pathlib import Path
from typing import Optional


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration (H:MM or M:SS)."""
    if seconds < 0:
        return "calculating..."

    seconds = int(seconds)
    if seconds >= 3600:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        return f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"


class ProgressLogger:
    """Log progress at regular intervals with ETA calculation."""

    def __init__(
        self,
        logger: logging.Logger,
        total: int,
        task: str,
        min_interval: float = 20.0,
    ):
        self.logger = logger
        self.total = total
        self.task = task
        self.min_interval = min_interval

        self.start_time = time.monotonic()
        self.last_log_time = 0.0
        self.current = 0

        # For rate limiting adjustments
        self.pause_time = 0.0

    def add_pause_time(self, seconds: float):
        """Add pause time (e.g., rate limit waits) to exclude from rate calculation."""
        self.pause_time += seconds

    def update(self, current: int, force: bool = False):
        """Update progress and log if interval has passed."""
        self.current = current
        now = time.monotonic()

        # Log if interval has passed or if forced (start/end)
        if not force and (now - self.last_log_time) < self.min_interval:
            return

        self.last_log_time = now

        # Calculate progress
        elapsed = now - self.start_time
        active_time = elapsed - self.pause_time  # Time actually spent downloading

        if current > 0 and active_time > 0:
            rate = current / active_time
            remaining_items = self.total - current
            estimated_remaining = remaining_items / rate if rate > 0 else -1
        else:
            estimated_remaining = -1

        pct = (current / self.total * 100) if self.total > 0 else 0

        self.logger.info(
            "%s: %d/%d (%.0f%%) | %s elapsed | ETA %s",
            self.task,
            current,
            self.total,
            pct,
            format_duration(elapsed),
            format_duration(estimated_remaining),
        )

    def complete(self):
        """Log completion message."""
        elapsed = time.monotonic() - self.start_time
        self.logger.info(
            "%s complete: %d/%d (100%%) | %s total",
            self.task,
            self.total,
            self.total,
            format_duration(elapsed),
        )


def configure_logging(
    verbose: bool = False,
    log_file: Optional[Path] = None,
) -> logging.Logger:
    """Configure logging for the application.

    Args:
        verbose: If True, show DEBUG messages on console
        log_file: Optional path to also write logs to file

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("naruhodo")
    logger.setLevel(logging.DEBUG)

    # Close and remove existing handlers to avoid leaking file descriptors
    for handler in logger.handlers[:]:
        handler.close()
        logger.removeHandler(handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_format = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger
