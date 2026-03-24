"""Tests for logging_config module."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.logging_config import (
    format_duration,
    ProgressLogger,
    configure_logging,
)


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_negative_calculating(self):
        assert format_duration(-1) == "calculating..."
        assert format_duration(-100) == "calculating..."

    def test_zero(self):
        assert format_duration(0) == "0:00"

    def test_seconds_only(self):
        assert format_duration(30) == "0:30"
        assert format_duration(59) == "0:59"

    def test_minutes(self):
        assert format_duration(60) == "1:00"
        assert format_duration(90) == "1:30"
        assert format_duration(3599) == "59:59"

    def test_hours(self):
        assert format_duration(3600) == "1:00:00"
        assert format_duration(7200) == "2:00:00"
        assert format_duration(5400) == "1:30:00"

    def test_complex_duration(self):
        # 1 hour, 23 minutes, 45 seconds = 5025 seconds
        assert format_duration(5025) == "1:23:45"

    def test_float_input(self):
        assert format_duration(90.7) == "1:30"


class TestProgressLogger:
    """Tests for ProgressLogger class."""

    @pytest.fixture
    def mock_logger(self):
        return MagicMock(spec=logging.Logger)

    def test_initialization(self, mock_logger):
        progress = ProgressLogger(mock_logger, total=100, task="Test")
        assert progress.total == 100
        assert progress.task == "Test"
        assert progress.current == 0

    def test_default_min_interval(self, mock_logger):
        progress = ProgressLogger(mock_logger, total=100, task="Test")
        assert progress.min_interval == 20.0

    def test_custom_min_interval(self, mock_logger):
        progress = ProgressLogger(mock_logger, total=100, task="Test", min_interval=5.0)
        assert progress.min_interval == 5.0

    @patch("src.logging_config.time.monotonic")
    def test_respects_min_interval(self, mock_time, mock_logger):
        mock_time.return_value = 0.0
        progress = ProgressLogger(mock_logger, total=100, task="Test", min_interval=20.0)

        # First update - should not log (interval not passed)
        mock_time.return_value = 10.0
        progress.update(10)
        assert not mock_logger.info.called

    @patch("src.logging_config.time.monotonic")
    def test_logs_after_interval(self, mock_time, mock_logger):
        mock_time.return_value = 0.0
        progress = ProgressLogger(mock_logger, total=100, task="Test", min_interval=20.0)

        # Update after interval passed - should log
        mock_time.return_value = 25.0
        progress.update(50)
        assert mock_logger.info.called

    @patch("src.logging_config.time.monotonic")
    def test_force_update(self, mock_time, mock_logger):
        mock_time.return_value = 0.0
        progress = ProgressLogger(mock_logger, total=100, task="Test", min_interval=20.0)

        # Force update - should log immediately
        mock_time.return_value = 1.0
        progress.update(10, force=True)
        assert mock_logger.info.called

    @patch("src.logging_config.time.monotonic")
    def test_complete(self, mock_time, mock_logger):
        mock_time.return_value = 0.0
        progress = ProgressLogger(mock_logger, total=100, task="Test")

        mock_time.return_value = 60.0
        progress.complete()

        mock_logger.info.assert_called()
        call_args = mock_logger.info.call_args[0]
        assert "complete" in call_args[0]
        assert "100%" in call_args[0]

    def test_add_pause_time(self, mock_logger):
        progress = ProgressLogger(mock_logger, total=100, task="Test")
        assert progress.pause_time == 0.0

        progress.add_pause_time(60.0)
        assert progress.pause_time == 60.0

        progress.add_pause_time(30.0)
        assert progress.pause_time == 90.0


class TestConfigureLogging:
    """Tests for configure_logging function."""

    def test_returns_logger(self):
        logger = configure_logging()
        assert isinstance(logger, logging.Logger)
        assert logger.name == "naruhodo"

    def test_sets_debug_level(self):
        logger = configure_logging()
        assert logger.level == logging.DEBUG

    def test_verbose_mode(self):
        logger = configure_logging(verbose=True)
        # Check that console handler exists and has DEBUG level
        console_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert len(console_handlers) >= 1
        assert console_handlers[0].level == logging.DEBUG

    def test_normal_mode(self):
        logger = configure_logging(verbose=False)
        console_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
        assert len(console_handlers) >= 1
        assert console_handlers[0].level == logging.INFO

    def test_with_log_file(self, tmp_path):
        log_file = tmp_path / "logs" / "test.log"
        logger = configure_logging(log_file=log_file)

        # Log something
        logger.info("Test message")

        # Check file handlers
        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        assert len(file_handlers) >= 1
        assert log_file.exists()

    def test_clears_existing_handlers(self):
        # Configure twice
        logger1 = configure_logging()
        handler_count_1 = len(logger1.handlers)

        logger2 = configure_logging()
        handler_count_2 = len(logger2.handlers)

        # Handler count should be the same (not accumulating)
        assert handler_count_1 == handler_count_2

    def test_log_file_creates_parent_dirs(self, tmp_path):
        log_file = tmp_path / "nested" / "dir" / "test.log"
        configure_logging(log_file=log_file)
        assert log_file.parent.exists()
