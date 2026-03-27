"""Speaker diarization for Naruhodo podcast transcripts.

Provides speaker diarization via pyannote and speaker identification
via pluggable LLMs (Ollama, Claude).

Includes VTT parsing for diarization alignment with YouTube captions.

Requires optional dependencies:
    pip install naruhodo-transcripts[diarize]
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("naruhodo")

# Default LLM for speaker identification (override with --llm flag)
DEFAULT_LLM = "ollama:qwen2.5:72b-instruct-q4_K_M"


# --- HuggingFace token ---


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


# --- Diarization pipeline ---


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


# --- Transcript/diarization merge ---


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


# --- Speaker identification ---


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


# --- Audio duration ---


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


# --- Add diarization to transcript ---


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


# --- VTT parsing ---


def parse_vtt_to_segments(vtt_path: Path) -> list[dict]:
    """Parse VTT timestamps into segment dicts for diarization alignment.

    Reads a YouTube VTT file and converts it into a list of segment
    dictionaries compatible with the diarization merge functions.

    Args:
        vtt_path: Path to a .vtt file

    Returns:
        List of dicts with keys: start (float), end (float), text (str)
    """
    content = vtt_path.read_text(encoding="utf-8", errors="replace")
    segments = []
    current_start = None
    current_end = None
    current_lines = []

    # Regex for VTT timestamp lines: "00:00:01.234 --> 00:00:05.678"
    timestamp_re = re.compile(
        r"(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{1,2}:)?(\d{2}):(\d{2})\.(\d{3})"
    )

    for line in content.split("\n"):
        line = line.strip()

        # Skip header lines
        if not line or line == "WEBVTT":
            continue
        if line.startswith("Kind:") or line.startswith("Language:") or line.startswith("NOTE"):
            continue
        # Skip cue identifiers (numeric lines)
        if re.match(r"^\d+$", line):
            continue

        match = timestamp_re.match(line)
        if match:
            # Save previous segment
            if current_start is not None and current_lines:
                text = " ".join(current_lines)
                # Strip VTT tags like <c>, </c>, <00:00:01.234>, etc.
                text = re.sub(r"<[^>]+>", "", text).strip()
                if text:
                    segments.append({
                        "start": current_start,
                        "end": current_end,
                        "text": text,
                    })

            # Parse new timestamps
            h1 = int(match.group(1).rstrip(":")) if match.group(1) else 0
            m1 = int(match.group(2))
            s1 = int(match.group(3))
            ms1 = int(match.group(4))
            current_start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0

            h2 = int(match.group(5).rstrip(":")) if match.group(5) else 0
            m2 = int(match.group(6))
            s2 = int(match.group(7))
            ms2 = int(match.group(8))
            current_end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0

            current_lines = []
        else:
            # Text line
            current_lines.append(line)

    # Don't forget the last segment
    if current_start is not None and current_lines:
        text = " ".join(current_lines)
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text:
            segments.append({
                "start": current_start,
                "end": current_end,
                "text": text,
            })

    # Deduplicate consecutive identical text segments (YouTube VTT repeats lines)
    deduped = []
    for seg in segments:
        if not deduped or seg["text"] != deduped[-1]["text"]:
            deduped.append(seg)
        else:
            # Extend the end time of the previous segment
            deduped[-1]["end"] = seg["end"]

    return deduped
