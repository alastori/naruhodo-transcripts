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

# Ollama defaults
OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_OLLAMA_MODEL = "qwen2.5:72b-instruct-q4_K_M"

# Speaker identification prompt template
_SPEAKER_ID_PROMPT = """You are analyzing a transcript from the Naruhodo podcast, a Brazilian Portuguese science podcast.

The regular hosts are:
- **Ken Fujioka**: the curious layperson who asks questions, presents topics, reads listener messages
- **Altay de Souza** (Dr.): the scientist who explains and gives the scientific perspective

Some episodes also feature:
- **Reginaldo Cursino**: the audio engineer who occasionally participates in discussions
- Guest specialists who explain topics in their domain

The transcript has anonymous speaker labels (SPEAKER_00, SPEAKER_01). Based on the content, speaking patterns, and any self-introductions, determine which label corresponds to which person. Use actual names when you can identify them.

Respond ONLY with valid JSON:
{{"SPEAKER_00": "name", "SPEAKER_01": "name", "confidence": "high" or "medium" or "low", "evidence": "brief explanation"}}

Transcript:
{transcript}"""

_SPEAKER_ID_PROMPT_INTERVIEW = """You are analyzing a transcript from a Naruhodo podcast interview episode. In interviews, Ken Fujioka interviews a guest one-on-one (Altay de Souza is NOT present).

The speakers are:
- **Ken Fujioka**: the interviewer who asks questions, introduces the guest, and guides the conversation
- **{guest_name}**: the interview guest who answers questions and shares their expertise

The transcript has anonymous speaker labels. Based on the content, speaking patterns, and any introductions, determine which label corresponds to which person.

Respond ONLY with valid JSON:
{{"SPEAKER_00": "Ken Fujioka" or "{guest_name}", "SPEAKER_01": "Ken Fujioka" or "{guest_name}", "confidence": "high" or "medium" or "low", "evidence": "brief explanation"}}

Transcript:
{transcript}"""


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

    return {
        "text": text,
        "segments": segments,
        "language": result.get("language", "pt"),
        "word_count": len(text.split()),
        "duration_seconds": duration,
    }


def save_transcript_markdown(
    output_path: Path,
    audio_path: Path,
    result: dict,
    model: str,
) -> None:
    """Save Whisper transcription result as markdown file."""
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
    """Load pyannote speaker diarization pipeline. Returns None on failure."""
    try:
        import torch
        import warnings
        from pyannote.audio import Pipeline

        hf_token = get_hf_token()
        if not hf_token:
            logger.error("No HuggingFace token found. Set HF_TOKEN env var.")
            return None

        # PyTorch 2.6+ fix: trust pyannote model checkpoints from HuggingFace
        _original_torch_load = torch.load
        def _safe_torch_load(*args, **kwargs):
            kwargs["weights_only"] = False
            return _original_torch_load(*args, **kwargs)

        torch.load = _safe_torch_load
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pipeline = Pipeline.from_pretrained(
                    "pyannote/speaker-diarization-3.1",
                    use_auth_token=hf_token,
                )
        finally:
            torch.load = _original_torch_load

        if torch.backends.mps.is_available():
            pipeline = pipeline.to(torch.device("mps"))

        return pipeline

    except ImportError:
        logger.error("pyannote.audio not installed. Run: pip install naruhodo-transcripts[diarize]")
        return None
    except Exception as e:
        logger.error("Could not load diarization pipeline: %s", e)
        return None


def diarize_audio(
    pipeline,
    audio_path: Path,
    num_speakers: int = 2,
) -> list[tuple[float, float, str]]:
    """Run speaker diarization.

    Args:
        pipeline: pyannote diarization pipeline
        audio_path: Path to audio file
        num_speakers: Expected number of speakers (2 for regular, 3 for interviews)

    Returns list of (start, end, speaker) tuples.
    """
    diarization = pipeline(str(audio_path), num_speakers=num_speakers)
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
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
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
    episode_type: str = "regular",
    guest_name: str = "",
) -> dict:
    """Use Ollama to identify which SPEAKER_XX is Ken vs Altay (and guest for interviews).

    Returns dict with keys: mapping (dict of speaker labels to names),
    confidence (str), and evidence (str).
    """
    import requests as req

    # Condense to first ~2000 words for the LLM
    lines = []
    word_count = 0
    for speaker, text in labeled_segments:
        lines.append(f"[{speaker}]: {text}")
        word_count += len(text.split())
        if word_count > 2000:
            break

    if episode_type == "interview" and guest_name:
        prompt = _SPEAKER_ID_PROMPT_INTERVIEW.format(
            guest_name=guest_name,
            transcript="\n\n".join(lines),
        )
    else:
        prompt = _SPEAKER_ID_PROMPT.format(transcript="\n\n".join(lines))

    try:
        resp = req.post(OLLAMA_URL, json={
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=300)
        resp.raise_for_status()

        raw = resp.json().get("response", "").strip().strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        mapping = json.loads(raw)
        return {
            "mapping": {
                "SPEAKER_00": mapping.get("SPEAKER_00", "SPEAKER_00"),
                "SPEAKER_01": mapping.get("SPEAKER_01", "SPEAKER_01"),
            },
            "confidence": mapping.get("confidence", "unknown"),
            "evidence": mapping.get("evidence", ""),
        }
    except Exception as e:
        logger.warning("Ollama speaker ID failed: %s", e)
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
    ollama_model: str = DEFAULT_OLLAMA_MODEL,
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
        labeled_segments, ollama_model,
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
