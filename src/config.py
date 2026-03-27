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
