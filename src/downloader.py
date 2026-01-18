"""YouTube transcript downloader with retry logic and rate limiting."""

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .logging_config import ProgressLogger

logger = logging.getLogger("naruhodo")


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 5
    initial_delay: float = 60.0  # 1 minute
    backoff_factor: float = 2.0  # Exponential backoff
    max_delay: float = 3600.0  # 1 hour cap
    rate_limit_delay: float = 3600.0  # Wait 1 hour on rate limit


@dataclass
class DownloadResult:
    """Result of a download attempt."""

    success: bool
    video_id: str
    output_path: Optional[Path] = None
    error: Optional[str] = None
    no_subtitles: bool = False
    rate_limited: bool = False


class TranscriptDownloader:
    """Download YouTube transcripts with retry and rate limiting support."""

    def __init__(
        self,
        output_dir: Path,
        retry_config: Optional[RetryConfig] = None,
        language: str = "pt",
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.retry_config = retry_config or RetryConfig()
        self.language = language

    def extract_video_id(self, url: str) -> Optional[str]:
        """Extract video ID from YouTube URL."""
        patterns = [
            r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
            r"^([a-zA-Z0-9_-]{11})$",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    def get_output_filename(self, video_id: str, title: str, index: int) -> str:
        """Generate output filename for transcript."""
        # Sanitize title for filesystem
        safe_title = re.sub(r'[<>:"/\\|?*]', "", title)
        safe_title = safe_title.replace(":", "：").replace("?", "？")
        safe_title = safe_title[:100]  # Limit length
        return f"{index:03d} - {safe_title}.{self.language}.vtt"

    def download_transcript(
        self,
        video_url: str,
        title: str,
        index: int,
    ) -> DownloadResult:
        """Download transcript for a single video with retry logic."""
        video_id = self.extract_video_id(video_url)
        if not video_id:
            return DownloadResult(
                success=False,
                video_id="unknown",
                error=f"Could not extract video ID from: {video_url}",
            )

        output_filename = self.get_output_filename(video_id, title, index)
        output_path = self.output_dir / output_filename

        # Check if already downloaded
        if output_path.exists():
            logger.debug("Already downloaded: %s", output_filename)
            return DownloadResult(
                success=True,
                video_id=video_id,
                output_path=output_path,
            )

        # Try to download with retry
        delay = self.retry_config.initial_delay
        last_error = None

        for attempt in range(self.retry_config.max_retries):
            result = self._attempt_download(video_url, video_id, output_path)

            if result.success or result.no_subtitles:
                return result

            if result.rate_limited:
                wait_time = self.retry_config.rate_limit_delay
                logger.warning(
                    "Rate limited on %s. Waiting %d seconds before retry...",
                    video_id,
                    int(wait_time),
                )
                time.sleep(wait_time)
                last_error = result.error
            else:
                # Regular error - exponential backoff
                if attempt < self.retry_config.max_retries - 1:
                    logger.warning(
                        "Download failed for %s (attempt %d/%d): %s. Retrying in %ds...",
                        video_id,
                        attempt + 1,
                        self.retry_config.max_retries,
                        result.error,
                        int(delay),
                    )
                    time.sleep(delay)
                    delay = min(delay * self.retry_config.backoff_factor, self.retry_config.max_delay)
                last_error = result.error

        return DownloadResult(
            success=False,
            video_id=video_id,
            error=f"Max retries exceeded. Last error: {last_error}",
        )

    def _attempt_download(
        self,
        video_url: str,
        video_id: str,
        output_path: Path,
    ) -> DownloadResult:
        """Single download attempt using yt-dlp."""
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub",
            "--sub-lang", self.language,
            "--sub-format", "vtt",
            "--output", str(output_path.with_suffix("")),
            "--no-warnings",
            "--quiet",
            video_url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # Check output for specific errors
            output = result.stdout + result.stderr

            if "HTTP Error 429" in output or "rate limit" in output.lower():
                return DownloadResult(
                    success=False,
                    video_id=video_id,
                    error="Rate limited",
                    rate_limited=True,
                )

            if "no subtitles" in output.lower() or "There are no subtitles" in output:
                logger.debug("No subtitles available for: %s", video_id)
                return DownloadResult(
                    success=False,
                    video_id=video_id,
                    error="No subtitles available",
                    no_subtitles=True,
                )

            # Check if file was created
            # yt-dlp adds language suffix, so check for the file
            expected_file = output_path
            if not expected_file.exists():
                # Try without the language in the middle (yt-dlp format variations)
                possible_files = list(self.output_dir.glob(f"{output_path.stem}*{self.language}*.vtt"))
                if possible_files:
                    expected_file = possible_files[0]

            if expected_file.exists():
                return DownloadResult(
                    success=True,
                    video_id=video_id,
                    output_path=expected_file,
                )

            # If no file and no specific error, return generic error
            error_msg = output.strip() if output.strip() else "Unknown error - no file created"
            return DownloadResult(
                success=False,
                video_id=video_id,
                error=error_msg[:200],
            )

        except subprocess.TimeoutExpired:
            return DownloadResult(
                success=False,
                video_id=video_id,
                error="Download timed out",
            )
        except Exception as e:
            return DownloadResult(
                success=False,
                video_id=video_id,
                error=str(e),
            )


def estimate_cost(pending: int) -> dict:
    """Estimate time and resources for downloading pending episodes.

    Args:
        pending: Number of episodes to download

    Returns:
        Dictionary with cost estimates
    """
    download_time = pending * 3  # ~3 seconds per request
    rate_limits = pending // 60  # Rate limit expected every ~60 requests
    wait_time = rate_limits * 3600  # 1 hour per rate limit
    total_seconds = download_time + wait_time

    return {
        "requests": pending,
        "download_minutes": download_time // 60,
        "rate_limits": rate_limits,
        "wait_hours": rate_limits,  # 1 hour per rate limit
        "total_hours": round(total_seconds / 3600, 1),
    }


def sync_transcripts(
    episodes: list[dict],
    output_dir: Path,
    progress_logger: Optional[ProgressLogger] = None,
    retry_config: Optional[RetryConfig] = None,
) -> dict:
    """Sync transcripts for all episodes.

    Args:
        episodes: List of episode dictionaries with youtube_link
        output_dir: Directory to save transcripts
        progress_logger: Optional progress logger
        retry_config: Optional retry configuration

    Returns:
        Dictionary with sync results
    """
    downloader = TranscriptDownloader(output_dir, retry_config)

    results = {
        "downloaded": 0,
        "skipped": 0,
        "failed": 0,
        "no_subtitles": 0,
        "errors": [],
    }

    for i, episode in enumerate(episodes, 1):
        youtube_link = episode.get("youtube_link", "")

        if not youtube_link:
            results["skipped"] += 1
            continue

        title = episode.get("title", f"Episode {i}")
        result = downloader.download_transcript(youtube_link, title, i)

        if result.success:
            results["downloaded"] += 1
        elif result.no_subtitles:
            results["no_subtitles"] += 1
        else:
            results["failed"] += 1
            results["errors"].append({
                "video_id": result.video_id,
                "title": title,
                "error": result.error,
            })

        if progress_logger:
            progress_logger.update(i)

    if progress_logger:
        progress_logger.complete()

    return results
