#!/usr/bin/env python3
"""Transcribe missing Naruhodo episodes using local MLX Whisper.

Downloads MP3 audio from RSS enclosure URLs and transcribes using
the transcribe_audio.py tool from tidb-pm-tools (MLX Whisper, large-v3).

Optionally adds speaker diarization (pyannote) and speaker identification
(Ollama) to label who says what — Ken Fujioka or Altay de Souza.

Usage:
    # Transcribe all missing episodes
    python scripts/whisper_transcribe.py

    # Transcribe with speaker diarization
    python scripts/whisper_transcribe.py --diarize

    # Transcribe first 5 missing episodes (test run)
    python scripts/whisper_transcribe.py --limit 5

    # Transcribe a specific episode by number
    python scripts/whisper_transcribe.py --episode 400

    # Dry run (show what would be transcribed)
    python scripts/whisper_transcribe.py --dry-run

Requirements:
    - MLX Whisper installed (pip install mlx-whisper)
    - ffmpeg installed
    - tidb-pm-tools repo at ~/GitHub/alastori/tidb-pm-tools
    For --diarize:
    - pyannote.audio installed (pip install pyannote.audio)
    - HuggingFace token with access to pyannote/speaker-diarization-3.1
      and pyannote/segmentation-3.0 (stored in 1Password AI-Agents vault)
    - Ollama running locally with a model (e.g., qwen2.5:72b)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EPISODES_JSON = DATA_DIR / "episodes.json"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
AUDIO_CACHE_DIR = PROJECT_ROOT / "temp" / "audio"

# tidb-pm-tools transcription tool
TRANSCRIBE_TOOL = (
    Path.home() / "GitHub" / "alastori" / "tidb-pm-tools"
    / "tools" / "primitives" / "audio-transcribe" / "transcribe_audio.py"
)

# Vocabulary hint for Whisper — helps with proper noun recognition
INITIAL_PROMPT = (
    "Naruhodo, Ken Fujioka, Altay de Souza, Altay, Ken, "
    "podcast, ciência, neurociência, psicologia, comportamento, "
    "B9, Naruhodo podcast"
)

# Ollama config
OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen2.5:72b-instruct-q4_K_M"

# Speaker identification prompt
SPEAKER_ID_PROMPT = """You are analyzing a transcript from the Naruhodo podcast. This is a Brazilian Portuguese science podcast with two hosts:
- **Ken Fujioka**: the curious layperson who asks questions, presents topics, and reads listener messages
- **Altay de Souza** (Dr.): the scientist who explains, gives the scientific perspective, and provides deeper analysis

The transcript below has two anonymous speaker labels (SPEAKER_00 and SPEAKER_01). Based on the content, speaking patterns, and any self-introductions (e.g., "Eu sou o Ken Fujioka", "Eu sou o Altay de Souza"), determine which label corresponds to which host.

Respond ONLY with valid JSON:
{{"SPEAKER_00": "Ken Fujioka" or "Altay de Souza", "SPEAKER_01": "Ken Fujioka" or "Altay de Souza", "confidence": "high" or "medium" or "low", "evidence": "brief explanation"}}

Transcript:
{transcript}"""


def load_episodes() -> list[dict]:
    """Load episodes from JSON file."""
    return json.loads(EPISODES_JSON.read_text(encoding="utf-8"))


def get_missing_episodes(episodes: list[dict]) -> list[dict]:
    """Get episodes that need transcription, sorted by episode number."""
    missing = [
        ep for ep in episodes
        if ep.get("status") != "✅ Downloaded" and ep.get("audio_url")
    ]
    # Also check for existing .md transcripts (resume support)
    missing = [ep for ep in missing if not _transcript_exists(ep)]
    # Sort by episode number (newest first for relevance)
    missing.sort(key=lambda ep: int(ep.get("episode_number") or 0), reverse=True)
    return missing


def _transcript_exists(ep: dict) -> bool:
    """Check if a transcript already exists for this episode (.vtt or .md)."""
    title = ep.get("title", "")
    safe_title = _sanitize_filename(title)
    for ext in (".md", ".vtt"):
        for f in TRANSCRIPTS_DIR.iterdir() if TRANSCRIPTS_DIR.exists() else []:
            if f.suffix == ext and safe_title[:50] in f.name:
                return True
    return False


def _sanitize_filename(title: str) -> str:
    """Create a filesystem-safe filename from episode title."""
    safe = title.replace(":", "\uff1a").replace("?", "\uff1f")
    safe = re.sub(r'[<>"/\\|*]', "", safe)
    return safe[:100]


def _get_output_filename(ep: dict) -> str:
    """Generate output filename for Whisper transcript."""
    title = ep.get("title", "Unknown")
    safe_title = _sanitize_filename(title)
    num_match = re.search(r"#(\d+)", title)
    prefix = f"{int(num_match.group(1)):03d}" if num_match else "000"
    return f"{prefix} - {safe_title}.whisper.md"


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
        print(f"    Download failed: {e}")
        return False


def transcribe_audio(audio_path: Path, output_path: Path, model: str) -> dict:
    """Transcribe audio using tidb-pm-tools transcribe_audio.py."""
    cmd = [
        sys.executable,
        str(TRANSCRIBE_TOOL),
        str(audio_path),
        "--language", "pt",
        "--model", model,
        "--initial-prompt", INITIAL_PROMPT,
        "--output", str(output_path),
        "--quiet",
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=7200,
    )

    if result.returncode != 0:
        return {"status": "error", "error": result.stderr[:500]}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        if output_path.exists():
            return {"status": "success", "word_count": 0}
        return {"status": "error", "error": "No output produced"}


# --- Diarization ---


def _get_hf_token() -> str:
    """Get HuggingFace token from 1Password AI-Agents vault."""
    result = subprocess.run(
        ["op", "read", "op://AI-Agents/HuggingFace/naruhodo-transcripts/token"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "Could not read HF token from 1Password. "
            "Run: op read 'op://AI-Agents/HuggingFace/naruhodo-transcripts/token'"
        )
    return result.stdout.strip()


def load_diarization_pipeline():
    """Load pyannote speaker diarization pipeline. Returns None on failure."""
    try:
        import torch
        import warnings
        warnings.filterwarnings("ignore")

        # PyTorch 2.6+ fix: trust pyannote model checkpoints from HuggingFace
        _original_torch_load = torch.load
        def _safe_torch_load(*args, **kwargs):
            kwargs["weights_only"] = False
            return _original_torch_load(*args, **kwargs)
        torch.load = _safe_torch_load

        from pyannote.audio import Pipeline

        hf_token = _get_hf_token()
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            use_auth_token=hf_token,
        )

        if torch.backends.mps.is_available():
            pipeline = pipeline.to(torch.device("mps"))

        return pipeline

    except Exception as e:
        print(f"    Warning: could not load diarization pipeline: {e}")
        return None


def diarize_audio(pipeline, audio_path: Path) -> list[tuple[float, float, str]]:
    """Run speaker diarization on audio file.

    Returns list of (start_sec, end_sec, speaker_label) tuples.
    """
    diarization = pipeline(str(audio_path), num_speakers=2)
    return [
        (turn.start, turn.end, speaker)
        for turn, _, speaker in diarization.itertracks(yield_label=True)
    ]


def merge_transcript_with_diarization(
    transcript_text: str,
    turns: list[tuple[float, float, str]],
    total_duration: float,
) -> str:
    """Merge plain transcript text with speaker diarization timestamps.

    Uses proportional word-to-time alignment to assign speaker labels.
    Returns speaker-labeled transcript text.
    """
    words = transcript_text.split()
    if not words or total_duration <= 0:
        return transcript_text

    words_per_sec = len(words) / total_duration

    labeled_segments = []
    current_speaker = None
    current_words = []

    for start, end, speaker in turns:
        if end - start < 0.3:
            continue
        word_start = int(start * words_per_sec)
        word_end = int(end * words_per_sec)
        segment_words = words[word_start:word_end]
        if not segment_words:
            continue

        if speaker == current_speaker:
            current_words.extend(segment_words)
        else:
            if current_words and current_speaker:
                labeled_segments.append((current_speaker, " ".join(current_words)))
            current_speaker = speaker
            current_words = list(segment_words)

    # Flush last segment
    if current_words and current_speaker:
        labeled_segments.append((current_speaker, " ".join(current_words)))

    return labeled_segments


def identify_speakers_with_ollama(
    labeled_segments: list[tuple[str, str]],
    ollama_model: str,
) -> dict[str, str]:
    """Use Ollama to identify which SPEAKER_XX is Ken vs Altay.

    Returns mapping like {"SPEAKER_00": "Ken Fujioka", "SPEAKER_01": "Altay de Souza"}.
    """
    import requests

    # Build a condensed transcript for the LLM (first ~2000 words)
    lines = []
    word_count = 0
    for speaker, text in labeled_segments:
        lines.append(f"[{speaker}]: {text}")
        word_count += len(text.split())
        if word_count > 2000:
            break

    condensed = "\n\n".join(lines)
    prompt = SPEAKER_ID_PROMPT.format(transcript=condensed)

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=120)
        resp.raise_for_status()

        raw = resp.json().get("response", "")
        # Extract JSON from response (handle markdown code blocks)
        raw = raw.strip().strip("`").strip()
        if raw.startswith("json"):
            raw = raw[4:].strip()
        mapping = json.loads(raw)
        return {
            "SPEAKER_00": mapping.get("SPEAKER_00", "SPEAKER_00"),
            "SPEAKER_01": mapping.get("SPEAKER_01", "SPEAKER_01"),
            "confidence": mapping.get("confidence", "unknown"),
            "evidence": mapping.get("evidence", ""),
        }
    except Exception as e:
        print(f"    Ollama speaker ID failed: {e}")
        return {
            "SPEAKER_00": "SPEAKER_00",
            "SPEAKER_01": "SPEAKER_01",
            "confidence": "failed",
            "evidence": str(e),
        }


def format_diarized_transcript(
    labeled_segments: list[tuple[str, str]],
    speaker_mapping: dict[str, str],
) -> str:
    """Format labeled segments into readable diarized transcript."""
    lines = []
    for speaker_label, text in labeled_segments:
        name = speaker_mapping.get(speaker_label, speaker_label)
        lines.append(f"**{name}:** {text}")
    return "\n\n".join(lines)


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
    ollama_model: str,
) -> dict:
    """Add speaker diarization to an existing Whisper transcript file.

    Appends a diarized section to the markdown file.
    Returns speaker mapping result.
    """
    # Read existing transcript
    content = output_path.read_text(encoding="utf-8")
    parts = content.split("---\n", 1)
    header = parts[0] + "---\n" if len(parts) > 1 else ""
    transcript_text = parts[-1].strip()

    # Run diarization
    turns = diarize_audio(diarization_pipeline, audio_path)
    total_duration = get_audio_duration(audio_path)

    # Merge with transcript
    labeled_segments = merge_transcript_with_diarization(
        transcript_text, turns, total_duration,
    )

    if not labeled_segments:
        return {"confidence": "failed", "evidence": "No segments produced"}

    # Identify speakers with Ollama
    speaker_mapping = identify_speakers_with_ollama(labeled_segments, ollama_model)

    # Format diarized transcript
    diarized_text = format_diarized_transcript(labeled_segments, speaker_mapping)

    # Rewrite the file with diarized version
    speaker_info = (
        f"**Speakers:** {speaker_mapping.get('SPEAKER_00', '?')} & "
        f"{speaker_mapping.get('SPEAKER_01', '?')} "
        f"(confidence: {speaker_mapping.get('confidence', '?')})\n"
    )

    new_content = header + speaker_info + "\n---\n\n" + diarized_text
    output_path.write_text(new_content, encoding="utf-8")

    return speaker_mapping


# --- Utilities ---


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


# --- Main ---


def main():
    parser = argparse.ArgumentParser(
        description="Transcribe missing Naruhodo episodes using local MLX Whisper"
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Maximum number of episodes to transcribe (0 = all)"
    )
    parser.add_argument(
        "--episode", type=str,
        help="Transcribe a specific episode by number (e.g., 400)"
    )
    parser.add_argument(
        "--model", type=str, default="large-v3",
        help="Whisper model to use (default: large-v3)"
    )
    parser.add_argument(
        "--diarize", action="store_true",
        help="Add speaker diarization (requires pyannote + Ollama)"
    )
    parser.add_argument(
        "--ollama-model", type=str, default=OLLAMA_MODEL,
        help=f"Ollama model for speaker identification (default: {OLLAMA_MODEL})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be transcribed without doing it"
    )
    parser.add_argument(
        "--keep-audio", action="store_true",
        help="Keep downloaded audio files after transcription"
    )
    args = parser.parse_args()

    # Verify transcription tool exists
    if not TRANSCRIBE_TOOL.exists():
        print(f"Error: transcribe_audio.py not found at {TRANSCRIBE_TOOL}")
        print("Make sure tidb-pm-tools is cloned at ~/GitHub/alastori/tidb-pm-tools")
        return 1

    # Load diarization pipeline if needed (do this early to fail fast)
    diarization_pipeline = None
    if args.diarize:
        print("Loading diarization pipeline...")
        diarization_pipeline = load_diarization_pipeline()
        if diarization_pipeline is None:
            print("Error: could not load diarization pipeline. Install pyannote.audio")
            print("and ensure HF token is in 1Password AI-Agents vault.")
            return 1
        print("Diarization pipeline ready.\n")

    # Load episodes and find missing
    episodes = load_episodes()
    missing = get_missing_episodes(episodes)

    if args.episode:
        missing = [ep for ep in missing if ep.get("episode_number") == args.episode]
        if not missing:
            all_eps = [ep for ep in episodes if ep.get("episode_number") == args.episode]
            if all_eps and all_eps[0].get("status") == "✅ Downloaded":
                print(f"Episode #{args.episode} already has a transcript.")
            elif all_eps:
                print(f"Episode #{args.episode} found but transcript may already exist.")
            else:
                print(f"Episode #{args.episode} not found.")
            return 0

    if args.limit > 0:
        missing = missing[:args.limit]

    if not missing:
        print("All episodes have transcripts!")
        return 0

    # Show plan
    total_audio = estimate_duration(missing)
    est_transcribe = total_audio * 0.3  # ~0.3x realtime on Apple Silicon

    print(f"\n🎙️  Naruhodo Whisper Transcription\n")
    print(f"  Episodes to transcribe:  {len(missing)}")
    print(f"  Total audio:             {format_duration(total_audio)}")
    print(f"  Model:                   {args.model}")
    print(f"  Diarization:             {'yes (pyannote + Ollama)' if args.diarize else 'no'}")
    print(f"  Est. transcription time: ~{format_duration(est_transcribe)}")
    print(f"  Est. download size:      ~{total_audio / 60:.0f} MB")
    print()

    if args.dry_run:
        print("Episodes that would be transcribed:")
        for ep in missing:
            print(f"  {ep.get('episode_number', '?'):>4}  {ep['title'][:70]}  ({ep.get('duration', '?')})")
        return 0

    # Create directories
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Process episodes
    results = {"success": 0, "failed": 0, "diarized": 0, "errors": []}
    start_time = time.monotonic()

    for i, ep in enumerate(missing, 1):
        title = ep.get("title", "Unknown")
        ep_num = ep.get("episode_number", "?")
        audio_url = ep["audio_url"]
        output_filename = _get_output_filename(ep)
        output_path = TRANSCRIPTS_DIR / output_filename

        print(f"[{i}/{len(missing)}] #{ep_num}: {title[:60]}")

        # Skip if output already exists
        if output_path.exists():
            print(f"    Skipping (already exists)")
            results["success"] += 1
            continue

        # Download audio
        audio_path = AUDIO_CACHE_DIR / f"naruhodo_{ep_num}.mp3"

        if not audio_path.exists():
            print(f"    Downloading audio...")
            if not download_audio(audio_url, audio_path):
                results["failed"] += 1
                results["errors"].append({"episode": ep_num, "error": "Download failed"})
                continue

        audio_size_mb = audio_path.stat().st_size / (1024 * 1024)
        print(f"    Audio: {audio_size_mb:.1f} MB")

        # Transcribe
        print(f"    Transcribing with {args.model}...")
        t0 = time.monotonic()
        result = transcribe_audio(audio_path, output_path, args.model)
        elapsed = time.monotonic() - t0

        if result.get("status") == "success":
            word_count = result.get("word_count", 0)
            quality = result.get("quality", {}).get("score", "N/A")
            print(f"    Transcribed: {word_count} words, quality={quality}, took {format_duration(elapsed)}")
            results["success"] += 1
        else:
            error = result.get("error", "Unknown error")
            print(f"    Failed: {error[:100]}")
            results["failed"] += 1
            results["errors"].append({"episode": ep_num, "error": error[:200]})
            if not args.keep_audio and audio_path.exists():
                audio_path.unlink()
            continue

        # Diarize if requested
        if args.diarize and diarization_pipeline and output_path.exists():
            print(f"    Diarizing...")
            t1 = time.monotonic()
            mapping = add_diarization_to_transcript(
                output_path, audio_path, diarization_pipeline, args.ollama_model,
            )
            d_elapsed = time.monotonic() - t1
            confidence = mapping.get("confidence", "?")
            s0 = mapping.get("SPEAKER_00", "?")
            s1 = mapping.get("SPEAKER_01", "?")
            print(f"    Speakers: {s0} & {s1} (confidence: {confidence}, took {format_duration(d_elapsed)})")
            results["diarized"] += 1

        # Clean up audio unless --keep-audio
        if not args.keep_audio and audio_path.exists():
            audio_path.unlink()

    # Summary
    total_time = time.monotonic() - start_time
    print(f"\n{'='*50}")
    print(f"Transcription complete in {format_duration(total_time)}")
    print(f"  Success:   {results['success']}")
    if args.diarize:
        print(f"  Diarized:  {results['diarized']}")
    print(f"  Failed:    {results['failed']}")

    if results["errors"]:
        print(f"\nErrors:")
        for err in results["errors"][:10]:
            print(f"  #{err['episode']}: {err['error'][:80]}")

    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
