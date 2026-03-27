"""Central configuration for naruhodo-transcripts."""

from pathlib import Path

# Project paths (relative to this file's location)
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
LOGS_DIR = PROJECT_ROOT / "temp" / "logs"
AUDIO_CACHE_DIR = PROJECT_ROOT / "temp" / "audio"
EPISODES_JSON = DATA_DIR / "episodes.json"
EPISODE_INDEX = DATA_DIR / "episode-index.md"

# RSS feed
RSS_FEED_URL = "https://feeds.simplecast.com/hwQVm5gy"
RSS_REQUEST_TIMEOUT = 30  # seconds
RSS_MAX_RETRIES = 3
RSS_INITIAL_RETRY_DELAY = 1.0  # seconds
RSS_RETRY_BACKOFF_FACTOR = 2.0

# YouTube
YOUTUBE_PLAYLIST_URL = "https://www.youtube.com/playlist?list=UUPzA7lZCeFiafe9V9bamISw"

# Downloader
SUBPROCESS_TIMEOUT = 120  # seconds for yt-dlp commands

# Rate limiting estimates
SECONDS_PER_DOWNLOAD = 3  # Average time per download request
DOWNLOADS_PER_RATE_LIMIT = 60  # Approximate number of downloads before rate limit
RATE_LIMIT_WAIT_SECONDS = 3600  # 1 hour wait after rate limit

# Default LLM for speaker identification and quality checks
DEFAULT_LLM = "ollama:qwen2.5:72b-instruct-q4_K_M"

# Known speakers for the Naruhodo podcast
KNOWN_SPEAKERS = {"Ken Fujioka", "Altay de Souza"}

# Quality thresholds (used by quality checks and transcription flagging)
QUALITY_MEAN_LOGPROB_THRESHOLD = -0.8
QUALITY_REPEATED_6GRAMS_THRESHOLD = 5
QUALITY_MIN_SPEAKER_TURNS = 10


# --- Episode naming ---

import re

_RE_UNSAFE_FILENAME = re.compile(r'[<>"/\\|*/]')


def episode_key(ep: dict) -> str:
    """Generate a stable key prefix for an episode: N400, E050, X010, R035.

    Used in filenames, lookups, and cross-referencing.
    """
    title = ep.get("title", "")
    ep_num = ep.get("episode_number", "")
    ep_type = ep.get("episode_type", "")

    if not ep_num:
        # Extract from title as fallback
        match = re.search(r"#(\d+)", title)
        ep_num = match.group(1) if match else ""

    # REPLAY/REPOST override: check title regardless of ep_type
    # because rss_parser classifies REPLAYs as "regular" (they match #N pattern)
    if "REPLAY" in title or "REPOST" in title:
        ep_type = "replay"
    elif not ep_type:
        if "Entrevista" in title:
            ep_type = "interview"
        elif "Extra" in title:
            ep_type = "extra"
        else:
            ep_type = "regular"

    prefix_map = {
        "regular": "N",
        "interview": "E",
        "extra": "X",
        "replay": "R",
        "other": "O",
    }
    letter = prefix_map.get(ep_type, "O")

    if ep_num:
        return f"{letter}{int(ep_num):03d}"
    return ""


def episode_filename(ep: dict, extension: str = "") -> str:
    """Generate a clean filename for an episode.

    Examples:
        N400 - Por que gostamos de música.pt.vtt
        E050 - Dr. Maria Santos.whisper.md
        X010 - Mobilidade elétrica.whisper.md
        R035 - Pessoas absorvem energia.pt.vtt
    """
    key = episode_key(ep)
    if not key:
        # Fallback for episodes without a number
        title = ep.get("title", "Unknown")
        safe = _sanitize_for_filename(title)
        return f"{safe}{extension}"

    topic = ep.get("topic", "")
    if not topic:
        # Derive from title
        title = ep.get("title", "")
        # Strip "Naruhodo #N - " or "Naruhodo Entrevista #N: " prefix
        topic = re.sub(
            r"^(?:REPLAY[:\s]*)?(?:REPOST[:\s]*)?Naruhodo\s*(?:Entrevista\s*|Extra\s*)?#?\d*\s*[-:\s]*",
            "", title, flags=re.IGNORECASE,
        ).strip()

    safe_topic = _sanitize_for_filename(topic)
    return f"{key} - {safe_topic}{extension}"


def _sanitize_for_filename(text: str) -> str:
    """Sanitize text for safe use in filenames."""
    safe = text.replace(":", "\uff1a").replace("?", "\uff1f")
    safe = _RE_UNSAFE_FILENAME.sub("", safe)
    return safe[:80]
