"""YouTube playlist discovery and episode matching for Naruhodo podcast."""

import json
import logging
import re
import subprocess
from dataclasses import dataclass

from .rss_parser import extract_episode_type

logger = logging.getLogger("naruhodo")


@dataclass
class YouTubeVideo:
    """Represents a video from the YouTube playlist."""
    video_id: str
    title: str
    url: str
    episode_type: str  # "regular", "interview", "extra", "other"
    episode_number: str


def parse_youtube_title(title: str) -> tuple[str, str]:
    """Parse YouTube video title to extract episode type and number.

    Args:
        title: YouTube video title

    Returns:
        Tuple of (episode_type, episode_number)
        - episode_type: "regular", "interview", "extra", or "other"
        - episode_number: The episode number as string, or ""

    Examples:
        "Naruhodo #457 - Topic" -> ("regular", "457")
        "Naruhodo Entrevista #58: Guest" -> ("interview", "58")
        "Naruhodo Extra #10 - Special" -> ("extra", "10")
    """
    # Interview episodes: "Naruhodo Entrevista #58"
    match = re.search(r"Naruhodo\s+Entrevista\s*#(\d+)", title, re.IGNORECASE)
    if match:
        return ("interview", match.group(1))

    # Extra episodes: "Naruhodo Extra #10"
    match = re.search(r"Naruhodo\s+Extra\s*#(\d+)", title, re.IGNORECASE)
    if match:
        return ("extra", match.group(1))

    # Regular episodes: "Naruhodo #457"
    match = re.search(r"Naruhodo\s*#(\d+)", title, re.IGNORECASE)
    if match:
        return ("regular", match.group(1))

    return ("other", "")


def get_episode_key(episode_type: str, episode_number: str) -> str:
    """Generate a unique key for an episode based on type and number.

    Args:
        episode_type: "regular", "interview", "extra", or "other"
        episode_number: The episode number

    Returns:
        Key string like "N457" for regular, "E58" for interview, "X10" for extra
    """
    if not episode_number:
        return ""

    type_prefix = {
        "regular": "N",
        "interview": "E",  # Entrevista
        "extra": "X",
    }
    prefix = type_prefix.get(episode_type, "")
    return f"{prefix}{episode_number}" if prefix else ""


def fetch_playlist_metadata(playlist_url: str) -> list[YouTubeVideo]:
    """Fetch video metadata from a YouTube playlist using yt-dlp.

    Args:
        playlist_url: URL of the YouTube playlist

    Returns:
        List of YouTubeVideo objects with metadata

    Raises:
        RuntimeError: If yt-dlp command fails
    """
    logger.info("Fetching playlist metadata from %s", playlist_url)

    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        playlist_url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,  # 5 minute timeout
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp failed: {e.stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("yt-dlp timed out after 5 minutes") from e

    videos = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            video_id = data.get("id", "")
            title = data.get("title", "")
            url = data.get("url") or f"https://www.youtube.com/watch?v={video_id}"

            episode_type, episode_number = parse_youtube_title(title)

            videos.append(YouTubeVideo(
                video_id=video_id,
                title=title,
                url=url,
                episode_type=episode_type,
                episode_number=episode_number,
            ))
        except json.JSONDecodeError:
            logger.warning("Failed to parse yt-dlp output line: %s", line[:100])
            continue

    logger.info("Found %d videos in playlist", len(videos))
    return videos


def match_episodes(
    episodes: list[dict],
    youtube_videos: list[YouTubeVideo],
) -> tuple[list[dict], dict]:
    """Match RSS episodes to YouTube videos by episode key.

    Args:
        episodes: List of episode dictionaries from RSS
        youtube_videos: List of YouTubeVideo objects from playlist

    Returns:
        Tuple of (updated_episodes, stats)
        - updated_episodes: Episodes list with youtube_link populated
        - stats: Dictionary with matching statistics
    """
    # Build lookup from RSS episodes using canonical extract_episode_type
    rss_by_key: dict[str, dict] = {}
    for ep in episodes:
        ep_type = extract_episode_type(ep.get("title", ""))
        ep_num = ep.get("episode_number", "")
        key = get_episode_key(ep_type, ep_num)
        if key:
            rss_by_key[key] = ep

    # Build lookup from YouTube videos
    yt_by_key: dict[str, YouTubeVideo] = {}
    for video in youtube_videos:
        key = get_episode_key(video.episode_type, video.episode_number)
        if key:
            yt_by_key[key] = video

    # Match and update
    matched = 0
    already_had_link = 0
    updated = 0

    for key, ep in rss_by_key.items():
        if key in yt_by_key:
            matched += 1
            video = yt_by_key[key]
            if ep.get("youtube_link"):
                already_had_link += 1
            else:
                ep["youtube_link"] = video.url
                updated += 1

    # Calculate unmatched
    rss_unmatched = set(rss_by_key.keys()) - set(yt_by_key.keys())
    yt_unmatched = set(yt_by_key.keys()) - set(rss_by_key.keys())

    # Count episodes without keys (other type)
    rss_no_key = sum(
        1 for ep in episodes
        if not get_episode_key(
            extract_episode_type(ep.get("title", "")),
            ep.get("episode_number", ""),
        )
    )
    yt_no_key = sum(1 for v in youtube_videos if not get_episode_key(v.episode_type, v.episode_number))

    stats = {
        "total_rss_episodes": len(episodes),
        "total_youtube_videos": len(youtube_videos),
        "matched": matched,
        "already_had_link": already_had_link,
        "newly_updated": updated,
        "rss_unmatched": len(rss_unmatched),
        "youtube_unmatched": len(yt_unmatched),
        "rss_no_key": rss_no_key,
        "youtube_no_key": yt_no_key,
        "rss_unmatched_keys": sorted(rss_unmatched),
        "youtube_unmatched_keys": sorted(yt_unmatched),
    }

    return episodes, stats
