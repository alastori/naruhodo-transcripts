"""Tests for youtube_discovery module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.youtube_discovery import (
    YouTubeVideo,
    parse_youtube_title,
    get_episode_key,
    fetch_playlist_metadata,
    match_episodes,
)
from src.rss_parser import extract_episode_type


class TestParseYoutubeTitle:
    """Tests for parse_youtube_title function."""

    def test_regular_episode(self):
        title = "Naruhodo #457 - Ficamos mais reflexivos e tristes no final do ano?"
        assert parse_youtube_title(title) == ("regular", "457")

    def test_regular_episode_no_space(self):
        title = "Naruhodo#123 - Tema do Episódio"
        assert parse_youtube_title(title) == ("regular", "123")

    def test_interview_episode(self):
        title = "Naruhodo Entrevista #58: Augusto César Ferreira De Moraes"
        assert parse_youtube_title(title) == ("interview", "58")

    def test_interview_episode_no_space_before_hash(self):
        title = "Naruhodo Entrevista#25: Guest Name"
        assert parse_youtube_title(title) == ("interview", "25")

    def test_extra_episode(self):
        title = "Naruhodo Extra #10 - Special Content"
        assert parse_youtube_title(title) == ("extra", "10")

    def test_extra_episode_no_space(self):
        title = "Naruhodo Extra#5 - Bonus"
        assert parse_youtube_title(title) == ("extra", "5")

    def test_other_format(self):
        title = "Some other video title"
        assert parse_youtube_title(title) == ("other", "")

    def test_naruhodo_without_number(self):
        title = "Naruhodo - Special Episode"
        assert parse_youtube_title(title) == ("other", "")

    def test_case_insensitive(self):
        title = "NARUHODO #100 - Test"
        assert parse_youtube_title(title) == ("regular", "100")

    def test_interview_case_insensitive(self):
        title = "naruhodo entrevista #20: Guest"
        assert parse_youtube_title(title) == ("interview", "20")


class TestGetEpisodeKey:
    """Tests for get_episode_key function."""

    def test_regular_episode_key(self):
        assert get_episode_key("regular", "457") == "N457"

    def test_interview_episode_key(self):
        assert get_episode_key("interview", "58") == "E58"

    def test_extra_episode_key(self):
        assert get_episode_key("extra", "10") == "X10"

    def test_unknown_type_no_key(self):
        assert get_episode_key("unknown", "123") == ""

    def test_other_type_no_key(self):
        assert get_episode_key("other", "123") == ""

    def test_empty_number_no_key(self):
        assert get_episode_key("regular", "") == ""

    def test_none_number_no_key(self):
        assert get_episode_key("regular", None) == ""


class TestExtractEpisodeType:
    """Tests for extract_episode_type (canonical, from rss_parser)."""

    def test_regular_episode(self):
        assert extract_episode_type("Naruhodo #457 - Test") == "regular"

    def test_interview_episode(self):
        assert extract_episode_type("Naruhodo Entrevista #58: Guest") == "interview"

    def test_extra_episode(self):
        assert extract_episode_type("Naruhodo Extra #10 - Bonus") == "extra"

    def test_other_episode(self):
        assert extract_episode_type("Some other title") == "other"


class TestFetchPlaylistMetadata:
    """Tests for fetch_playlist_metadata function."""

    @patch("src.youtube_discovery.subprocess.run")
    def test_successful_fetch(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = (
            '{"id": "abc123", "title": "Naruhodo #457 - Test", "url": null}\n'
            '{"id": "def456", "title": "Naruhodo Entrevista #58: Guest", "url": null}\n'
        )
        mock_run.return_value = mock_result

        videos = fetch_playlist_metadata("https://youtube.com/playlist?list=test")

        assert len(videos) == 2
        assert videos[0].video_id == "abc123"
        assert videos[0].episode_type == "regular"
        assert videos[0].episode_number == "457"
        assert videos[0].url == "https://www.youtube.com/watch?v=abc123"
        assert videos[1].video_id == "def456"
        assert videos[1].episode_type == "interview"
        assert videos[1].episode_number == "58"

    @patch("src.youtube_discovery.subprocess.run")
    def test_handles_url_in_response(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = '{"id": "abc123", "title": "Test", "url": "https://custom.url/video"}\n'
        mock_run.return_value = mock_result

        videos = fetch_playlist_metadata("https://youtube.com/playlist?list=test")

        assert videos[0].url == "https://custom.url/video"

    @patch("src.youtube_discovery.subprocess.run")
    def test_handles_empty_lines(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = '{"id": "abc123", "title": "Naruhodo #1 - Test", "url": null}\n\n\n'
        mock_run.return_value = mock_result

        videos = fetch_playlist_metadata("https://youtube.com/playlist?list=test")

        assert len(videos) == 1

    @patch("src.youtube_discovery.subprocess.run")
    def test_handles_invalid_json(self, mock_run):
        mock_result = MagicMock()
        mock_result.stdout = 'invalid json\n{"id": "abc123", "title": "Naruhodo #1", "url": null}\n'
        mock_run.return_value = mock_result

        videos = fetch_playlist_metadata("https://youtube.com/playlist?list=test")

        assert len(videos) == 1
        assert videos[0].video_id == "abc123"

    @patch("src.youtube_discovery.subprocess.run")
    def test_raises_on_subprocess_error(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "yt-dlp", stderr="Error")

        with pytest.raises(RuntimeError, match="yt-dlp failed"):
            fetch_playlist_metadata("https://youtube.com/playlist?list=test")

    @patch("src.youtube_discovery.subprocess.run")
    def test_raises_on_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("yt-dlp", 300)

        with pytest.raises(RuntimeError, match="timed out"):
            fetch_playlist_metadata("https://youtube.com/playlist?list=test")


class TestMatchEpisodes:
    """Tests for match_episodes function."""

    def test_basic_matching(self):
        episodes = [
            {"title": "Naruhodo #457 - Test", "episode_number": "457", "youtube_link": ""},
            {"title": "Naruhodo Entrevista #58: Guest", "episode_number": "58", "youtube_link": ""},
        ]
        youtube_videos = [
            YouTubeVideo("abc", "Naruhodo #457 - Test", "https://yt/abc", "regular", "457"),
            YouTubeVideo("def", "Naruhodo Entrevista #58: Guest", "https://yt/def", "interview", "58"),
        ]

        updated, stats = match_episodes(episodes, youtube_videos)

        assert updated[0]["youtube_link"] == "https://yt/abc"
        assert updated[1]["youtube_link"] == "https://yt/def"
        assert stats["matched"] == 2
        assert stats["newly_updated"] == 2

    def test_preserves_existing_links(self):
        episodes = [
            {"title": "Naruhodo #100 - Test", "episode_number": "100", "youtube_link": "https://existing"},
        ]
        youtube_videos = [
            YouTubeVideo("new", "Naruhodo #100 - Test", "https://yt/new", "regular", "100"),
        ]

        updated, stats = match_episodes(episodes, youtube_videos)

        assert updated[0]["youtube_link"] == "https://existing"
        assert stats["matched"] == 1
        assert stats["already_had_link"] == 1
        assert stats["newly_updated"] == 0

    def test_unmatched_rss_episodes(self):
        episodes = [
            {"title": "Naruhodo #100 - Test", "episode_number": "100", "youtube_link": ""},
            {"title": "Naruhodo #200 - Test", "episode_number": "200", "youtube_link": ""},
        ]
        youtube_videos = [
            YouTubeVideo("abc", "Naruhodo #100 - Test", "https://yt/abc", "regular", "100"),
        ]

        updated, stats = match_episodes(episodes, youtube_videos)

        assert stats["matched"] == 1
        assert stats["rss_unmatched"] == 1
        assert "N200" in stats["rss_unmatched_keys"]

    def test_unmatched_youtube_videos(self):
        episodes = [
            {"title": "Naruhodo #100 - Test", "episode_number": "100", "youtube_link": ""},
        ]
        youtube_videos = [
            YouTubeVideo("abc", "Naruhodo #100 - Test", "https://yt/abc", "regular", "100"),
            YouTubeVideo("def", "Naruhodo #200 - Extra", "https://yt/def", "regular", "200"),
        ]

        updated, stats = match_episodes(episodes, youtube_videos)

        assert stats["matched"] == 1
        assert stats["youtube_unmatched"] == 1
        assert "N200" in stats["youtube_unmatched_keys"]

    def test_handles_other_types(self):
        episodes = [
            {"title": "Some Special Episode", "episode_number": "", "youtube_link": ""},
        ]
        youtube_videos = [
            YouTubeVideo("abc", "Some Other Video", "https://yt/abc", "other", ""),
        ]

        updated, stats = match_episodes(episodes, youtube_videos)

        assert stats["matched"] == 0
        assert stats["rss_no_key"] == 1
        assert stats["youtube_no_key"] == 1

    def test_different_episode_types_dont_match(self):
        episodes = [
            {"title": "Naruhodo #50 - Regular", "episode_number": "50", "youtube_link": ""},
            {"title": "Naruhodo Entrevista #50: Guest", "episode_number": "50", "youtube_link": ""},
        ]
        youtube_videos = [
            YouTubeVideo("abc", "Naruhodo #50 - Regular", "https://yt/abc", "regular", "50"),
        ]

        updated, stats = match_episodes(episodes, youtube_videos)

        assert stats["matched"] == 1
        assert stats["rss_unmatched"] == 1
        # Interview E50 should be unmatched
        assert "E50" in stats["rss_unmatched_keys"]
        # Regular N50 was matched
        assert updated[0]["youtube_link"] == "https://yt/abc"
        assert updated[1]["youtube_link"] == ""  # Interview still empty

    def test_empty_inputs(self):
        episodes = []
        youtube_videos = []

        updated, stats = match_episodes(episodes, youtube_videos)

        assert updated == []
        assert stats["matched"] == 0
        assert stats["total_rss_episodes"] == 0
        assert stats["total_youtube_videos"] == 0
