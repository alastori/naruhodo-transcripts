#!/usr/bin/env python3
"""Transcribe missing Naruhodo episodes using local MLX Whisper.

Downloads MP3 audio from RSS enclosure URLs and transcribes using
the transcribe_audio.py tool from tidb-pm-tools (MLX Whisper, large-v3).

Usage:
    # Transcribe all missing episodes
    python scripts/whisper_transcribe.py

    # Transcribe first 5 missing episodes (test run)
    python scripts/whisper_transcribe.py --limit 5

    # Transcribe a specific episode by number
    python scripts/whisper_transcribe.py --episode 400

    # Use a different model
    python scripts/whisper_transcribe.py --model distil-large-v3

    # Dry run (show what would be transcribed)
    python scripts/whisper_transcribe.py --dry-run

Requirements:
    - MLX Whisper installed (pip install mlx-whisper)
    - ffmpeg installed
    - tidb-pm-tools repo at ~/GitHub/alastori/tidb-pm-tools
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EPISODES_JSON = DATA_DIR / "episodes.json"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
AUDIO_CACHE_DIR = PROJECT_ROOT / "temp" / "audio"

# tidb-pm-tools transcription tool
TRANSCRIBE_TOOL = Path.home() / "GitHub" / "alastori" / "tidb-pm-tools" / "tools" / "primitives" / "audio-transcribe" / "transcribe_audio.py"

# Vocabulary hint for Whisper — helps with proper noun recognition
INITIAL_PROMPT = (
    "Naruhodo, Ken Fujioka, Altay de Souza, Altay, Ken, "
    "podcast, ciência, neurociência, psicologia, comportamento, "
    "B9, Naruhodo podcast"
)


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
    missing = [
        ep for ep in missing
        if not _transcript_exists(ep)
    ]
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
    """Transcribe audio using tidb-pm-tools transcribe_audio.py.

    Returns the JSON result from the transcription tool.
    """
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
        cmd,
        capture_output=True,
        text=True,
        timeout=7200,  # 2 hour timeout per episode
    )

    if result.returncode != 0:
        return {"status": "error", "error": result.stderr[:500]}

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        # Output file was still created even if JSON parsing fails
        if output_path.exists():
            return {"status": "success", "word_count": 0}
        return {"status": "error", "error": "No output produced"}


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

    # Load episodes and find missing
    episodes = load_episodes()
    missing = get_missing_episodes(episodes)

    if args.episode:
        missing = [ep for ep in missing if ep.get("episode_number") == args.episode]
        if not missing:
            # Check if it already exists
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
    results = {"success": 0, "failed": 0, "errors": []}
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
        audio_ext = ".mp3"
        audio_path = AUDIO_CACHE_DIR / f"naruhodo_{ep_num}{audio_ext}"

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
            print(f"    Done: {word_count} words, quality={quality}, took {format_duration(elapsed)}")
            results["success"] += 1
        else:
            error = result.get("error", "Unknown error")
            print(f"    Failed: {error[:100]}")
            results["failed"] += 1
            results["errors"].append({"episode": ep_num, "error": error[:200]})

        # Clean up audio unless --keep-audio
        if not args.keep_audio and audio_path.exists():
            audio_path.unlink()

    # Summary
    total_time = time.monotonic() - start_time
    print(f"\n{'='*50}")
    print(f"Transcription complete in {format_duration(total_time)}")
    print(f"  Success: {results['success']}")
    print(f"  Failed:  {results['failed']}")

    if results["errors"]:
        print(f"\nErrors:")
        for err in results["errors"][:10]:
            print(f"  #{err['episode']}: {err['error'][:80]}")

    return 0 if results["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
