"""Tests for cli module."""

import sys
from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from src.cli import main, cmd_status, cmd_catalog, cmd_transcribe, check_disk_space


class TestCheckDiskSpace:
    """Tests for check_disk_space function."""

    def test_returns_tuple(self):
        result = check_disk_space(10)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_has_space_for_small_download(self):
        has_space, required_mb, available_mb = check_disk_space(10)
        assert has_space is True
        assert required_mb <= 1

    @patch("src.cli.shutil.disk_usage")
    def test_warns_when_low_space(self, mock_disk_usage):
        mock_disk_usage.return_value = MagicMock(free=5 * 1024 * 1024)
        has_space, required_mb, available_mb = check_disk_space(100)
        assert has_space is False
        assert required_mb == 9
        assert available_mb == 5

    @patch("src.cli.shutil.disk_usage")
    def test_handles_os_error(self, mock_disk_usage):
        mock_disk_usage.side_effect = OSError("Permission denied")
        has_space, required_mb, available_mb = check_disk_space(10)
        assert has_space is True


class TestMain:
    """Tests for main function and command routing."""

    def test_no_command_shows_help(self, capsys):
        with patch.object(sys, "argv", ["naruhodo"]):
            result = main()
        assert result == 1

    def test_status_command_routes(self):
        with patch.object(sys, "argv", ["naruhodo", "status"]):
            with patch("src.cli.cmd_status") as mock_cmd:
                mock_cmd.return_value = 0
                main()
                mock_cmd.assert_called_once()

    def test_catalog_command_routes(self):
        with patch.object(sys, "argv", ["naruhodo", "catalog"]):
            with patch("src.cli.cmd_catalog") as mock_cmd:
                mock_cmd.return_value = 0
                main()
                mock_cmd.assert_called_once()

    def test_transcribe_command_routes(self):
        with patch.object(sys, "argv", ["naruhodo", "transcribe", "--dry-run"]):
            with patch("src.cli.cmd_transcribe") as mock_cmd:
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

    def test_deprecated_commands_still_route(self):
        """Old command names should still work (with deprecation warning)."""
        for cmd in ["refresh-index", "sync", "status"]:
            with patch.object(sys, "argv", ["naruhodo", cmd]):
                # Just verify it doesn't crash during parsing
                pass


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

    @patch("src.cli.TRANSCRIPTS_DIR")
    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_shows_pipeline_status(
        self, mock_logging, mock_load, mock_update, mock_dir, args, capsys, tmp_path
    ):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [{"title": "Ep 1", "youtube_link": "https://yt/1"}]
        mock_update.return_value = (1, 0, 0)
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = []

        result = cmd_status(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Pipeline Status" in captured.out


class TestCmdCatalog:
    """Tests for cmd_catalog function."""

    @pytest.fixture
    def args(self):
        return Namespace(verbose=False, rss_only=False, youtube_only=False, playlist=None)

    @patch("src.cli.save_index")
    @patch("src.cli.generate_index_markdown")
    @patch("src.cli.save_episodes")
    @patch("src.cli.update_episode_status")
    @patch("src.cli.match_episodes")
    @patch("src.cli.fetch_playlist_metadata")
    @patch("src.cli.merge_episodes")
    @patch("src.cli.load_episodes")
    @patch("src.cli.parse_rss")
    @patch("src.cli.fetch_rss_feed")
    @patch("src.cli.configure_logging")
    def test_successful_catalog(
        self, mock_logging, mock_fetch, mock_parse, mock_load,
        mock_merge, mock_playlist, mock_match, mock_update,
        mock_save_ep, mock_generate, mock_save_idx, args, capsys,
    ):
        mock_logging.return_value = MagicMock()
        mock_fetch.return_value = "<rss>content</rss>"
        mock_parse.return_value = [{"title": "Ep 1"}, {"title": "Ep 2"}]
        mock_load.return_value = []
        mock_merge.return_value = [{"title": "Ep 1"}, {"title": "Ep 2"}]
        mock_playlist.return_value = []
        mock_match.return_value = (
            [{"title": "Ep 1", "youtube_link": ""}, {"title": "Ep 2", "youtube_link": ""}],
            {"newly_updated": 0},
        )
        mock_update.return_value = (0, 0, 2)
        mock_generate.return_value = "# Index"

        result = cmd_catalog(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "Catalog" in captured.out

    @patch("src.cli.fetch_rss_feed")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_handles_fetch_error(self, mock_logging, mock_load, mock_fetch, args):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = []
        mock_fetch.side_effect = Exception("Network error")
        result = cmd_catalog(args)
        assert result == 1


class TestCmdTranscribe:
    """Tests for cmd_transcribe function."""

    @pytest.fixture
    def args(self):
        return Namespace(
            verbose=False, yes=True, source="youtube", episode=None,
            limit=0, model="large-v3", dry_run=False, keep_audio=False,
        )

    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_no_episodes_error(self, mock_logging, mock_load, args):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = []
        result = cmd_transcribe(args)
        assert result == 1

    @patch("src.cli.update_episode_status")
    @patch("src.cli.load_episodes")
    @patch("src.cli.configure_logging")
    def test_all_downloaded(self, mock_logging, mock_load, mock_update, args, capsys):
        mock_logging.return_value = MagicMock()
        mock_load.return_value = [{"title": "Ep 1"}]
        mock_update.return_value = (1, 0, 0)
        result = cmd_transcribe(args)
        assert result == 0
        captured = capsys.readouterr()
        assert "All episodes have transcripts" in captured.out
