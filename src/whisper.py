"""Local Whisper transcription for Naruhodo episodes.

Provides high-quality transcription using MLX Whisper (Apple Silicon).
Speaker diarization has been moved to src/diarization.py.

Requires optional dependencies:
    pip install naruhodo-transcripts[whisper]     # transcription only
"""

import json
import logging
import re
import time
from pathlib import Path

from .config import AUDIO_CACHE_DIR, EPISODES_JSON, TRANSCRIPTS_DIR

logger = logging.getLogger("naruhodo")

# MLX Whisper model mapping
WHISPER_MODELS = {
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "distil-large-v3": "mlx-community/distil-whisper-large-v3",
    "medium": "mlx-community/whisper-medium-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "tiny": "mlx-community/whisper-tiny-mlx",
}

# Vocabulary hint for Whisper — helps with proper noun recognition
INITIAL_PROMPT = (
    "Naruhodo, Ken Fujioka, Altay de Souza, Altay, Ken, "
    "podcast, ciência, neurociência, psicologia, comportamento, "
    "B9, Naruhodo podcast"
)


# --- Episode helpers ---


def load_episodes() -> list[dict]:
    """Load episodes from JSON file."""
    return json.loads(EPISODES_JSON.read_text(encoding="utf-8"))


def get_missing_episodes(episodes: list[dict]) -> list[dict]:
    """Get episodes that need transcription, sorted by episode number (newest first)."""
    missing = [
        ep for ep in episodes
        if ep.get("status") != "\u2705 Downloaded"
        and ep.get("audio_url")
        and not _transcript_exists(ep)
    ]
    missing.sort(key=lambda ep: int(ep.get("episode_number") or 0), reverse=True)
    return missing


def _transcript_exists(ep: dict) -> bool:
    """Check if a transcript already exists for this episode (.vtt or .md)."""
    if not TRANSCRIPTS_DIR.exists():
        return False
    safe_title = sanitize_filename(ep.get("title", ""))
    search = safe_title[:50]
    for f in TRANSCRIPTS_DIR.iterdir():
        if f.suffix in (".md", ".vtt") and search in f.name:
            return True
    return False


def sanitize_filename(title: str) -> str:
    """Create a filesystem-safe filename from episode title."""
    safe = title.replace(":", "\uff1a").replace("?", "\uff1f")
    safe = re.sub(r'[<>"/\\|*]', "", safe)
    return safe[:100]


def get_output_filename(ep: dict) -> str:
    """Generate output filename for Whisper transcript."""
    title = ep.get("title", "Unknown")
    safe_title = sanitize_filename(title)
    num_match = re.search(r"#(\d+)", title)
    prefix = f"{int(num_match.group(1)):03d}" if num_match else "000"
    return f"{prefix} - {safe_title}.whisper.md"


def format_duration(seconds: float) -> str:
    """Format seconds as H:MM:SS."""
    h = int(seconds) // 3600
    m = (int(seconds) % 3600) // 60
    s = int(seconds) % 60
    return f"{h}:{m:02d}:{s:02d}"


def estimate_duration(episodes: list[dict]) -> float:
    """Estimate total audio duration in seconds."""
    total = 0
    for ep in episodes:
        dur = ep.get("duration", "")
        parts = dur.split(":")
        if len(parts) == 3:
            total += int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            total += int(parts[0]) * 60 + int(parts[1])
    return total


# --- Audio download ---


def download_audio(audio_url: str, output_path: Path) -> bool:
    """Download audio file from URL. Returns True on success."""
    try:
        import requests
        response = requests.get(audio_url, stream=True, timeout=120, allow_redirects=True)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        logger.error("Download failed: %s", e)
        return False


# --- Whisper transcription ---


def transcribe(audio_path: Path, model: str = "large-v3") -> dict:
    """Transcribe audio file using MLX Whisper.

    Args:
        audio_path: Path to audio file
        model: Whisper model name (large-v3, distil-large-v3, medium, small, etc.)

    Returns:
        Dict with keys: text, segments, language, word_count, duration_seconds
    """
    import mlx_whisper

    hf_repo = WHISPER_MODELS.get(model, model)

    result = mlx_whisper.transcribe(
        str(audio_path),
        path_or_hf_repo=hf_repo,
        language="pt",
        initial_prompt=INITIAL_PROMPT,
        word_timestamps=True,
    )

    text = result.get("text", "").strip()
    segments = result.get("segments", [])
    duration = segments[-1]["end"] if segments else 0.0

    # Extract quality metrics from segments
    quality = _compute_quality_metrics(segments, text, duration)

    return {
        "text": text,
        "segments": segments,
        "language": result.get("language", "pt"),
        "word_count": len(text.split()),
        "duration_seconds": duration,
        "quality": quality,
    }


def _compute_quality_metrics(
    segments: list[dict], text: str, duration: float
) -> dict:
    """Compute quality metrics from Whisper segments."""
    if not segments:
        return {}

    logprobs = [s.get("avg_logprob", 0) for s in segments]
    compressions = [s.get("compression_ratio", 0) for s in segments]
    no_speech = [s.get("no_speech_prob", 0) for s in segments]
    temperatures = [s.get("temperature", 0) for s in segments]

    # Word-level confidence
    word_probs = []
    for s in segments:
        for w in s.get("words", []):
            if "probability" in w:
                word_probs.append(w["probability"])

    word_count = len(text.split())
    wpm = (word_count / duration * 60) if duration > 0 else 0

    # Repeated n-gram detection (hallucination indicator)
    words = text.lower().split()
    ngram_size = 6
    ngrams = [" ".join(words[i:i+ngram_size]) for i in range(len(words) - ngram_size + 1)]
    from collections import Counter
    ngram_counts = Counter(ngrams)
    repeated_ngrams = sum(1 for count in ngram_counts.values() if count > 2)

    # Type-token ratio (vocabulary richness)
    unique_words = len(set(words))
    ttr = unique_words / len(words) if words else 0

    metrics = {
        "segment_count": len(segments),
        "mean_logprob": sum(logprobs) / len(logprobs),
        "min_logprob": min(logprobs),
        "mean_compression_ratio": sum(compressions) / len(compressions),
        "max_compression_ratio": max(compressions),
        "high_compression_segments": sum(1 for c in compressions if c > 2.0),
        "mean_no_speech_prob": sum(no_speech) / len(no_speech),
        "high_no_speech_segments": sum(1 for p in no_speech if p > 0.6),
        "fallback_segments": sum(1 for t in temperatures if t > 0),
        "words_per_minute": round(wpm, 1),
        "repeated_6grams": repeated_ngrams,
        "type_token_ratio": round(ttr, 3),
    }

    if word_probs:
        metrics["mean_word_probability"] = sum(word_probs) / len(word_probs)
        metrics["low_confidence_words"] = sum(1 for p in word_probs if p < 0.5)
        metrics["low_confidence_ratio"] = metrics["low_confidence_words"] / len(word_probs)

    return metrics


def save_transcript_markdown(
    output_path: Path,
    audio_path: Path,
    result: dict,
    model: str,
) -> None:
    """Save Whisper transcription result as markdown file and quality sidecar JSON."""
    duration = result["duration_seconds"]
    minutes = int(duration) // 60
    seconds = int(duration) % 60

    content = f"""# Transcript

**Source:** {audio_path.name}
**Duration:** {minutes}:{seconds:02d}
**Words:** {result['word_count']:,}
**Model:** {model}

---

{result['text']}
"""
    output_path.write_text(content, encoding="utf-8")

    # Save segments sidecar JSON (for later diarization alignment)
    segments = result.get("segments", [])
    if segments:
        segments_path = output_path.with_suffix(".segments.json")
        segments_path.write_text(
            json.dumps(segments, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Save quality sidecar JSON
    quality = result.get("quality", {})
    if quality:
        quality_path = output_path.with_suffix(".quality.json")
        quality_data = {
            "episode": output_path.stem,
            "model": model,
            "word_count": result["word_count"],
            "duration_seconds": duration,
            "metrics": quality,
        }
        quality_path.write_text(
            json.dumps(quality_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


# Re-export diarization functions for backward compatibility
from .diarization import (  # noqa: F401, E402
    DEFAULT_LLM,
    add_diarization_to_transcript,
    diarize_audio,
    get_audio_duration,
    get_hf_token,
    identify_speakers,
    load_diarization_pipeline,
    merge_transcript_with_diarization,
    parse_vtt_to_segments,
)
