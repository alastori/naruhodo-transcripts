"""Local Whisper transcription and speaker diarization for Naruhodo episodes.

Provides high-quality transcription using MLX Whisper (Apple Silicon)
with optional speaker diarization via pyannote + Ollama.

Requires optional dependencies:
    pip install naruhodo-transcripts[whisper]     # transcription only
    pip install naruhodo-transcripts[diarize]     # transcription + diarization
"""

import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

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

# Default LLM for speaker identification (override with --llm flag)
DEFAULT_LLM = "ollama:qwen2.5:72b-instruct-q4_K_M"


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


# --- Speaker diarization ---


def get_hf_token() -> Optional[str]:
    """Get HuggingFace token from HF_TOKEN env var or 1Password."""
    token = os.environ.get("HF_TOKEN")
    if token:
        return token

    # Fallback: 1Password
    try:
        result = subprocess.run(
            ["op", "read", "op://AI-Agents/HuggingFace/naruhodo-transcripts/token"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def load_diarization_pipeline():
    """Load pyannote speaker diarization pipeline (community-1, requires pyannote 4.0+).

    Returns None on failure.
    """
    try:
        import warnings
        from pyannote.audio import Pipeline

        hf_token = get_hf_token()
        if not hf_token:
            logger.error("No HuggingFace token found. Set HF_TOKEN env var.")
            return None

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-community-1",
                token=hf_token,
            )

        # MPS (Apple Silicon GPU) is safe with community-1 on pyannote 4.0
        import torch
        if torch.backends.mps.is_available():
            pipeline = pipeline.to(torch.device("mps"))

        return pipeline

    except ImportError:
        logger.error("pyannote.audio not installed. Run: uv sync --extra diarize")
        return None
    except Exception as e:
        logger.error("Could not load diarization pipeline: %s", e)
        return None


def _ensure_wav(audio_path: Path) -> Path:
    """Convert audio to 16kHz mono WAV if needed (pyannote 4.0 is strict about sample alignment)."""
    if audio_path.suffix == ".wav":
        return audio_path
    wav_path = audio_path.with_suffix(".wav")
    if wav_path.exists():
        return wav_path
    subprocess.run(
        ["ffmpeg", "-i", str(audio_path), "-ar", "16000", "-ac", "1", str(wav_path), "-y"],
        capture_output=True, timeout=120,
    )
    return wav_path


def diarize_audio(
    pipeline,
    audio_path: Path,
    num_speakers: int = 2,
) -> list[tuple[float, float, str]]:
    """Run speaker diarization.

    Args:
        pipeline: pyannote diarization pipeline
        audio_path: Path to audio file
        num_speakers: Expected number of speakers

    Returns list of (start, end, speaker) tuples.
    """
    wav_path = _ensure_wav(audio_path)
    output = pipeline(str(wav_path), num_speakers=num_speakers)

    # pyannote 4.0 returns DiarizeOutput; 3.x returned Annotation directly
    annotation = getattr(output, "speaker_diarization", output)
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in annotation.itertracks(yield_label=True)
    ]


def merge_transcript_with_diarization(
    whisper_segments: list[dict],
    turns: list[tuple[float, float, str]],
) -> list[tuple[str, str]]:
    """Merge Whisper segments with speaker diarization using timestamps.

    Uses Whisper's word-level timestamps for accurate alignment rather
    than proportional word distribution.

    Args:
        whisper_segments: Whisper output segments with 'start', 'end', 'text' keys
        turns: Speaker diarization turns from pyannote

    Returns list of (speaker_label, text) tuples.
    """
    if not whisper_segments or not turns:
        text = " ".join(s.get("text", "") for s in whisper_segments)
        return [("SPEAKER_00", text.strip())] if text.strip() else []

    def _get_speaker_at(timestamp: float) -> str:
        """Find which speaker is active at a given timestamp."""
        best_speaker = "SPEAKER_00"
        best_overlap = 0.0
        for start, end, speaker in turns:
            # How much does this turn overlap with a small window around timestamp?
            overlap = max(0, min(end, timestamp + 0.5) - max(start, timestamp - 0.5))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = speaker
        return best_speaker

    segments = []
    current_speaker = None
    current_words = []

    for seg in whisper_segments:
        # Use word-level timestamps if available, otherwise segment-level
        words = seg.get("words", [])
        if words:
            for word_info in words:
                ts = word_info.get("start", seg.get("start", 0))
                word = word_info.get("word", "").strip()
                if not word:
                    continue
                speaker = _get_speaker_at(ts)
                if speaker == current_speaker:
                    current_words.append(word)
                else:
                    if current_words and current_speaker:
                        segments.append((current_speaker, " ".join(current_words)))
                    current_speaker = speaker
                    current_words = [word]
        else:
            # Fallback: use segment midpoint
            midpoint = (seg.get("start", 0) + seg.get("end", 0)) / 2
            text = seg.get("text", "").strip()
            if not text:
                continue
            speaker = _get_speaker_at(midpoint)
            if speaker == current_speaker:
                current_words.extend(text.split())
            else:
                if current_words and current_speaker:
                    segments.append((current_speaker, " ".join(current_words)))
                current_speaker = speaker
                current_words = text.split()

    if current_words and current_speaker:
        segments.append((current_speaker, " ".join(current_words)))

    return segments


def identify_speakers(
    labeled_segments: list[tuple[str, str]],
    llm_spec: str = DEFAULT_LLM,
    episode_type: str = "regular",
    guest_name: str = "",
) -> dict:
    """Identify which SPEAKER_XX is Ken vs Altay using a pluggable LLM.

    Args:
        labeled_segments: List of (speaker_label, text) tuples
        llm_spec: LLM provider:model spec (e.g., "ollama:qwen2.5:72b", "claude:sonnet")
        episode_type: "regular" or "interview"
        guest_name: Guest name for interview episodes

    Returns dict with keys: mapping, confidence, evidence.
    """
    from .llm import llm_call, load_prompt

    # Condense to first ~2000 words for the LLM
    lines = []
    word_count = 0
    for speaker, text in labeled_segments:
        lines.append(f"[{speaker}]: {text}")
        word_count += len(text.split())
        if word_count > 2000:
            break

    transcript = "\n\n".join(lines)

    try:
        if episode_type == "interview" and guest_name:
            prompt = load_prompt("speaker_id_interview",
                                 guest_name=guest_name, transcript=transcript)
        else:
            prompt = load_prompt("speaker_id_regular", transcript=transcript)

        result = llm_call(llm_spec, prompt)

        return {
            "mapping": {
                "SPEAKER_00": result.get("SPEAKER_00", "SPEAKER_00"),
                "SPEAKER_01": result.get("SPEAKER_01", "SPEAKER_01"),
            },
            "confidence": result.get("confidence", "unknown"),
            "evidence": result.get("evidence", ""),
        }
    except Exception as e:
        logger.warning("Speaker ID failed (%s): %s", llm_spec, e)
        return {
            "mapping": {
                "SPEAKER_00": "SPEAKER_00",
                "SPEAKER_01": "SPEAKER_01",
            },
            "confidence": "failed",
            "evidence": str(e),
        }


def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(audio_path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def add_diarization_to_transcript(
    output_path: Path,
    audio_path: Path,
    diarization_pipeline,
    whisper_segments: list[dict],
    llm_spec: str = DEFAULT_LLM,
    episode_type: str = "regular",
    guest_name: str = "",
) -> dict:
    """Add speaker labels to an existing Whisper transcript file.

    Uses Whisper's word-level timestamps for accurate speaker alignment.

    Returns speaker mapping result.
    """
    content = output_path.read_text(encoding="utf-8")
    parts = content.split("---\n", 1)
    header = parts[0] + "---\n" if len(parts) > 1 else ""

    # Interviews are Ken + guest (2 speakers). Regular episodes are Ken + Altay (2 speakers).
    turns = diarize_audio(diarization_pipeline, audio_path, num_speakers=2)

    labeled_segments = merge_transcript_with_diarization(whisper_segments, turns)

    if not labeled_segments:
        return {"mapping": {}, "confidence": "failed", "evidence": "No segments produced"}

    speaker_result = identify_speakers(
        labeled_segments, llm_spec=llm_spec,
        episode_type=episode_type, guest_name=guest_name,
    )
    name_map = speaker_result["mapping"]

    # Format diarized transcript
    diarized_lines = []
    for speaker_label, text in labeled_segments:
        name = name_map.get(speaker_label, speaker_label)
        diarized_lines.append(f"**{name}:** {text}")

    # Build speaker info line from actual mapping values
    speaker_names = [n for n in name_map.values() if n]
    speaker_info = (
        f"**Speakers:** {' & '.join(speaker_names)} "
        f"(confidence: {speaker_result.get('confidence', '?')})\n"
    )

    new_content = header + speaker_info + "\n---\n\n" + "\n\n".join(diarized_lines)
    output_path.write_text(new_content, encoding="utf-8")

    return speaker_result
