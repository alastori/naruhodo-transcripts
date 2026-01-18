"""Tests for cli module."""

import sys
from argparse import Namespace
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from src.cli import (
    main,
    cmd_status,
    cmd_refresh_index,
    cmd_sync,
    check_disk_space,
)


class TestCheckDiskSpace:
    """Tests for check_disk_space function."""

    def test_returns_tuple(self):
        result = check_disk_space(10)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_has_space_for_small_download(self):
        has_space, required_mb, available_mb = check_disk_space(10)
        # 10 files * 100KB = 1MB required - should have space on any system
        assert has_space is True
        assert required_mb <= 1

    @patch("src.cli.shutil.disk_usage")
    def test_warns_when_low_space(self, mock_disk_usage):
        # Simulate 5MB free space
        mock_disk_usage.return_value = MagicMock(free=5 * 1024 * 1024)

        # Request 100 files = 10MB required
        has_space, required_mb, available_mb = check_disk_space(100)

        assert has_space is False
        assert required_mb == 9  # 100 * 100KB / 1024 ≈ 9MB
        assert available_mb == 5

    @patch("src.cli.shutil.disk_usage")
    def test_handles_os_error(self, mock_disk_usage):
        mock_disk_usage.side_effect = OSError("Permission denied")

        has_space, required_mb, available_mb = check_disk_space(10)

        # Should assume we have space if check fails
        assert has_space is True


class TestMain:
    """Tests for main function."""

    def test_no_command_shows_help(self, capsys):
        with patch.object(sys, "argv", ["naruhodo"]):
            result = main()

        assert result == 1
        captured = capsys.readouterr()
        assert "usage" in captured.out.lower() or "help" in captured.out.lower()

    def test_status_command_routes_correctly(self):
        with patch.object(sys, "argv", ["naruhodo", "status"]):
            with patch("src.cli.cmd_status") as mock_cmd:
                mock_cmd.return_value = 0
                main()
                mock_cmd.assert_called_once()

    def test_refresh_index_command_routes_correctly(self):
        with patch.object(sys, "argv", ["naruhodo", "refresh-index"]):
            with patch("src.cli.cmd_refresh_index") as mock_cmd:
                mock_cmd.return_value = 0
                main()
                mock_cmd.assert_called_once()

    def test_sync_command_routes_correctly(self):
        with patch.object(sys, "argv", ["naruhodo", "sync", "-y"]):
            with patch("src.cli.cmd_sync") as mock_cmd:
                mock_cmd.return_value = 0
                main()
                mock_cmd.assert_called_once()

    def test_verbose_flag_parsed(self):
        with patch.object(sys, "argv", ["naruhodo", "-v", "status"]):
            with patch("src.cli.cmd_status") as mock_cmd:
                mock_cmd.return_value = 0
                main()
                args = mock_cmd.call_args[0][0]
                assert args.verbose is True


class TestCmdStatus:
    """Tests for cmd_status function."""

    @pytest.fixture
    def args(self):
        return Namespace(verbose=False)

    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_no_episodes_returns_error(self, mock_logging, mock_load, args, capsys):
        mock_load.return_value = []
        mock_logging.return_value = MagicMock()

        result = cmd_status(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "No episodes found" in captured.out

    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_shows_status_with_pending(
        self, mock_logging, mock_load, mock_update, args, capsys
    ):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [{"title": "Episode 1"}]
        mock_update.return_value = (50, 100, 10)  # downloaded, pending, no_link

        result = cmd_status(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "50" in captured.out  # downloaded
        assert "100" in captured.out  # pending
        assert "10" in captured.out  # no_link

    @patch("src.cli.estimate_cost")
    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_shows_cost_estimate_when_pending(
        self, mock_logging, mock_load, mock_update, mock_cost, args, capsys
    ):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [{"title": "Episode 1"}]
        mock_update.return_value = (0, 10, 0)  # downloaded, pending, no_link
        mock_cost.return_value = {
            "requests": 10,
            "download_minutes": 1,
            "rate_limits": 0,
            "wait_hours": 0,
            "total_hours": 0.1,
        }

        cmd_status(args)

        captured = capsys.readouterr()
        assert "Estimated cost" in captured.out


class TestCmdRefreshIndex:
    """Tests for cmd_refresh_index function."""

    @pytest.fixture
    def args(self):
        return Namespace(verbose=False)

    @patch("src.cli.save_index")
    @patch("src.cli.generate_index_markdown")
    @patch("src.cli.save_episodes")
    @patch("src.cli.update_episode_status")
    @patch("src.cli.merge_episodes")
    @patch("src.cli.load_episodes")
    @patch("src.cli.parse_rss")
    @patch("src.cli.fetch_rss_feed")
    @patch("src.cli.configure_logging")
    def test_successful_refresh(
        self,
        mock_logging,
        mock_fetch,
        mock_parse,
        mock_load,
        mock_merge,
        mock_update,
        mock_save_ep,
        mock_generate,
        mock_save_idx,
        args,
        capsys,
    ):
        mock_logging.return_value = MagicMock()
        mock_fetch.return_value = "<rss>content</rss>"
        mock_parse.return_value = [{"title": "Ep 1"}, {"title": "Ep 2"}]
        mock_load.return_value = []
        mock_merge.return_value = [{"title": "Ep 1"}, {"title": "Ep 2"}]
        mock_update.return_value = (1, 1, 0)  # downloaded, pending, no_link
        mock_generate.return_value = "# Index"

        result = cmd_refresh_index(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Updated 2 episodes" in captured.out

    @patch("src.cli.fetch_rss_feed")
    @patch("src.cli.configure_logging")
    def test_handles_fetch_error(self, mock_logging, mock_fetch, args, capsys):
        mock_logging.return_value = MagicMock()
        mock_fetch.side_effect = Exception("Network error")

        result = cmd_refresh_index(args)

        assert result == 1


class TestCmdSync:
    """Tests for cmd_sync function."""

    @pytest.fixture
    def args(self):
        return Namespace(verbose=False, yes=True)

    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_no_episodes_error(self, mock_logging, mock_load, args, capsys):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = []

        result = cmd_sync(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "No episodes found" in captured.out

    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_all_downloaded_no_action(self, mock_logging, mock_load, mock_update, args, capsys):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [
            {"title": "Ep 1", "status": "✅ Downloaded", "youtube_link": ""},
        ]
        mock_update.return_value = (1, 0, 0)  # downloaded, pending, no_link

        result = cmd_sync(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "already downloaded" in captured.out.lower()

    @patch("src.cli.save_index")
    @patch("src.cli.generate_index_markdown")
    @patch("src.cli.save_episodes")
    @patch("src.cli.sync_transcripts")
    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_sync_with_pending(
        self,
        mock_logging,
        mock_load,
        mock_update,
        mock_sync,
        mock_save_ep,
        mock_generate,
        mock_save_idx,
        args,
        capsys,
    ):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [
            {"title": "Ep 1", "status": "⬜ Pending", "youtube_link": "https://youtube.com/watch?v=abc"},
        ]
        mock_update.return_value = (0, 1, 0)  # downloaded, pending, no_link
        mock_sync.return_value = {
            "downloaded": 1,
            "skipped": 0,
            "no_subtitles": 0,
            "failed": 0,
            "errors": [],
        }
        mock_generate.return_value = "# Index"

        result = cmd_sync(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Sync complete" in captured.out

    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_sync_requires_confirmation_without_yes(
        self, mock_logging, mock_load, mock_update, capsys
    ):
        args = Namespace(verbose=False, yes=False)
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [
            {"title": "Ep 1", "status": "⬜ Pending", "youtube_link": "https://youtube.com/watch?v=abc"},
        ]
        mock_update.return_value = (0, 1, 0)  # downloaded, pending, no_link

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            with patch("builtins.input", return_value="n"):
                result = cmd_sync(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Aborted" in captured.out

    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_sync_non_interactive_without_yes_flag(
        self, mock_logging, mock_load, mock_update, capsys
    ):
        args = Namespace(verbose=False, yes=False)
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [
            {"title": "Ep 1", "status": "⬜ Pending", "youtube_link": "https://youtube.com/watch?v=abc"},
        ]
        mock_update.return_value = (0, 1, 0)  # downloaded, pending, no_link

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            result = cmd_sync(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "non-interactive" in captured.out.lower()
        assert "--yes" in captured.out or "-y" in captured.out
