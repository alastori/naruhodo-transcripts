"""Tests for downloader module."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.downloader import (
    RetryConfig,
    DownloadResult,
    TranscriptDownloader,
    estimate_cost,
    sync_transcripts,
)


class TestRetryConfig:
    """Tests for RetryConfig dataclass."""

    def test_default_values(self):
        config = RetryConfig()
        assert config.max_retries == 5
        assert config.initial_delay == 60.0
        assert config.backoff_factor == 2.0
        assert config.max_delay == 3600.0
        assert config.rate_limit_delay == 3600.0

    def test_custom_values(self):
        config = RetryConfig(
            max_retries=3,
            initial_delay=30.0,
            backoff_factor=1.5,
            max_delay=1800.0,
            rate_limit_delay=1800.0,
        )
        assert config.max_retries == 3
        assert config.initial_delay == 30.0
        assert config.backoff_factor == 1.5
        assert config.max_delay == 1800.0
        assert config.rate_limit_delay == 1800.0


class TestDownloadResult:
    """Tests for DownloadResult dataclass."""

    def test_success_result(self, tmp_path):
        result = DownloadResult(
            success=True,
            video_id="abc123def45",
            output_path=tmp_path / "transcript.vtt",
        )
        assert result.success is True
        assert result.video_id == "abc123def45"
        assert result.error is None
        assert result.no_subtitles is False
        assert result.rate_limited is False

    def test_failure_result(self):
        result = DownloadResult(
            success=False,
            video_id="abc123def45",
            error="Download failed",
        )
        assert result.success is False
        assert result.error == "Download failed"

    def test_no_subtitles_result(self):
        result = DownloadResult(
            success=False,
            video_id="abc123def45",
            error="No subtitles available",
            no_subtitles=True,
        )
        assert result.success is False
        assert result.no_subtitles is True
        assert result.rate_limited is False

    def test_rate_limited_result(self):
        result = DownloadResult(
            success=False,
            video_id="abc123def45",
            error="Rate limited",
            rate_limited=True,
        )
        assert result.success is False
        assert result.rate_limited is True
        assert result.no_subtitles is False


class TestTranscriptDownloaderExtractVideoId:
    """Tests for TranscriptDownloader.extract_video_id method."""

    @pytest.fixture
    def downloader(self, tmp_path):
        return TranscriptDownloader(tmp_path)

    def test_standard_url(self, downloader):
        url = "https://www.youtube.com/watch?v=abc123def45"
        assert downloader.extract_video_id(url) == "abc123def45"

    def test_short_url(self, downloader):
        url = "https://youtu.be/abc123def45"
        assert downloader.extract_video_id(url) == "abc123def45"

    def test_url_with_params(self, downloader):
        url = "https://www.youtube.com/watch?v=abc123def45&t=120"
        assert downloader.extract_video_id(url) == "abc123def45"

    def test_embed_url(self, downloader):
        url = "https://www.youtube.com/embed/abc123def45"
        assert downloader.extract_video_id(url) is None  # /embed/ not in pattern

    def test_v_url(self, downloader):
        url = "https://www.youtube.com/v/abc123def45"
        assert downloader.extract_video_id(url) == "abc123def45"

    def test_bare_video_id(self, downloader):
        video_id = "abc123def45"
        assert downloader.extract_video_id(video_id) == "abc123def45"

    def test_invalid_url(self, downloader):
        url = "https://example.com/not-youtube"
        assert downloader.extract_video_id(url) is None

    def test_invalid_id_length(self, downloader):
        url = "https://www.youtube.com/watch?v=short"
        assert downloader.extract_video_id(url) is None


class TestTranscriptDownloaderGetOutputFilename:
    """Tests for TranscriptDownloader.get_output_filename method."""

    @pytest.fixture
    def downloader(self, tmp_path):
        return TranscriptDownloader(tmp_path)

    def test_basic_filename(self, downloader):
        filename = downloader.get_output_filename("abc", "Episode Title", 1)
        assert filename == "001 - Episode Title.pt.vtt"

    def test_sanitizes_special_chars(self, downloader):
        filename = downloader.get_output_filename("abc", "Title: With? Special* Chars", 1)
        assert ":" not in filename or "：" in filename
        assert "?" not in filename or "？" in filename
        assert "*" not in filename

    def test_truncates_long_titles(self, downloader):
        long_title = "A" * 200
        filename = downloader.get_output_filename("abc", long_title, 1)
        # Title should be truncated to 100 chars
        assert len(filename) <= 120  # 3 (index) + 3 (" - ") + 100 (title) + extension

    def test_index_padding(self, downloader):
        assert downloader.get_output_filename("abc", "Title", 1).startswith("001")
        assert downloader.get_output_filename("abc", "Title", 10).startswith("010")
        assert downloader.get_output_filename("abc", "Title", 100).startswith("100")


class TestTranscriptDownloaderDownloadTranscript:
    """Tests for TranscriptDownloader.download_transcript method."""

    @pytest.fixture
    def downloader(self, tmp_path):
        return TranscriptDownloader(tmp_path, RetryConfig(max_retries=1))

    def test_skips_existing_file(self, tmp_path):
        downloader = TranscriptDownloader(tmp_path)

        # Create existing file
        existing = tmp_path / "001 - Test Title.pt.vtt"
        existing.write_text("WEBVTT\n")

        result = downloader.download_transcript(
            "https://www.youtube.com/watch?v=abc123def45",
            "Test Title",
            1,
        )

        assert result.success is True
        assert result.output_path == existing

    def test_handles_invalid_url(self, downloader):
        result = downloader.download_transcript(
            "not-a-valid-url",
            "Test Title",
            1,
        )

        assert result.success is False
        assert "Could not extract video ID" in result.error

    @patch("src.downloader.subprocess.run")
    def test_successful_download(self, mock_run, tmp_path):
        downloader = TranscriptDownloader(tmp_path)

        # Create the output file as if yt-dlp created it
        output_file = tmp_path / "001 - Test Title.pt.vtt"

        def create_file(*args, **kwargs):
            output_file.write_text("WEBVTT\n")
            return MagicMock(stdout="", stderr="", returncode=0)

        mock_run.side_effect = create_file

        result = downloader.download_transcript(
            "https://www.youtube.com/watch?v=abc123def45",
            "Test Title",
            1,
        )

        assert result.success is True

    @patch("src.downloader.subprocess.run")
    def test_handles_no_subtitles(self, mock_run, tmp_path):
        downloader = TranscriptDownloader(tmp_path, RetryConfig(max_retries=1))

        mock_run.return_value = MagicMock(
            stdout="",
            stderr="no subtitles available for this video",
            returncode=1,
        )

        result = downloader.download_transcript(
            "https://www.youtube.com/watch?v=abc123def45",
            "Test Title",
            1,
        )

        assert result.success is False
        assert result.no_subtitles is True

    @patch("src.downloader.subprocess.run")
    def test_handles_rate_limit(self, mock_run, tmp_path):
        downloader = TranscriptDownloader(tmp_path, RetryConfig(max_retries=1, rate_limit_delay=0.01))

        mock_run.return_value = MagicMock(
            stdout="",
            stderr="HTTP Error 429: Too Many Requests",
            returncode=1,
        )

        result = downloader.download_transcript(
            "https://www.youtube.com/watch?v=abc123def45",
            "Test Title",
            1,
        )

        # After max retries, the final result won't have rate_limited=True
        # but the error message should mention rate limiting
        assert result.success is False
        assert "Rate limited" in result.error

    @patch("src.downloader.subprocess.run")
    def test_handles_timeout(self, mock_run, tmp_path):
        downloader = TranscriptDownloader(tmp_path, RetryConfig(max_retries=1))

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="yt-dlp", timeout=120)

        result = downloader.download_transcript(
            "https://www.youtube.com/watch?v=abc123def45",
            "Test Title",
            1,
        )

        assert result.success is False
        assert "timed out" in result.error.lower()


class TestEstimateCost:
    """Tests for estimate_cost function."""

    def test_zero_pending(self):
        cost = estimate_cost(0)
        assert cost["requests"] == 0
        assert cost["download_minutes"] == 0
        assert cost["rate_limits"] == 0
        assert cost["total_hours"] == 0.0

    def test_small_batch(self):
        cost = estimate_cost(30)
        assert cost["requests"] == 30
        assert cost["download_minutes"] == 1  # 30 * 3 / 60
        assert cost["rate_limits"] == 0  # 30 / 60 = 0
        assert cost["wait_hours"] == 0

    def test_large_batch_with_rate_limits(self):
        cost = estimate_cost(120)
        assert cost["requests"] == 120
        assert cost["download_minutes"] == 6  # 120 * 3 / 60
        assert cost["rate_limits"] == 2  # 120 / 60
        assert cost["wait_hours"] == 2
        # Total: 6 min download + 2 hours wait
        assert cost["total_hours"] == 2.1  # (360 + 7200) / 3600 = 2.1

    def test_edge_case_60(self):
        cost = estimate_cost(60)
        assert cost["requests"] == 60
        assert cost["rate_limits"] == 1


class TestSyncTranscripts:
    """Tests for sync_transcripts function."""

    def test_skips_episodes_without_youtube_link(self, tmp_path, sample_episode):
        episode_no_link = sample_episode.copy()
        episode_no_link["youtube_link"] = ""

        results = sync_transcripts([episode_no_link], tmp_path)

        assert results["skipped"] == 1
        assert results["downloaded"] == 0

    @patch("src.downloader.TranscriptDownloader.download_transcript")
    def test_counts_successful_downloads(self, mock_download, tmp_path, sample_episode):
        mock_download.return_value = DownloadResult(
            success=True,
            video_id="abc123def45",
            output_path=tmp_path / "transcript.vtt",
        )

        results = sync_transcripts([sample_episode], tmp_path)

        assert results["downloaded"] == 1
        assert results["failed"] == 0

    @patch("src.downloader.TranscriptDownloader.download_transcript")
    def test_counts_no_subtitles(self, mock_download, tmp_path, sample_episode):
        mock_download.return_value = DownloadResult(
            success=False,
            video_id="abc123def45",
            error="No subtitles",
            no_subtitles=True,
        )

        results = sync_transcripts([sample_episode], tmp_path)

        assert results["no_subtitles"] == 1

    @patch("src.downloader.TranscriptDownloader.download_transcript")
    def test_counts_failures(self, mock_download, tmp_path, sample_episode):
        mock_download.return_value = DownloadResult(
            success=False,
            video_id="abc123def45",
            error="Generic error",
        )

        results = sync_transcripts([sample_episode], tmp_path)

        assert results["failed"] == 1
        assert len(results["errors"]) == 1
        assert results["errors"][0]["error"] == "Generic error"

    @patch("src.downloader.TranscriptDownloader.download_transcript")
    def test_calls_progress_logger(self, mock_download, tmp_path, sample_episode):
        mock_download.return_value = DownloadResult(
            success=True,
            video_id="abc123def45",
        )

        mock_progress = MagicMock()

        results = sync_transcripts([sample_episode], tmp_path, progress_logger=mock_progress)

        mock_progress.update.assert_called()
        mock_progress.complete.assert_called_once()
