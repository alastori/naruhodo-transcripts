#!/usr/bin/env python3
"""CLI for Naruhodo podcast transcript pipeline.

Pipeline stages:
    catalog    → Fetch episode metadata (RSS + YouTube matching)
    transcribe → Get transcripts (YouTube captions or Whisper fallback)
    diarize    → Add speaker labels (works on any transcript)
    status     → Show pipeline state and quality summary
"""

import argparse
import functools
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure print output is visible immediately when piped (e.g., tee, CI logs)
print = functools.partial(print, flush=True)

from .config import (
    AUDIO_CACHE_DIR,
    DATA_DIR,
    EPISODE_INDEX,
    EPISODES_JSON,
    LOGS_DIR,
    TRANSCRIPTS_DIR,
    YOUTUBE_PLAYLIST_URL,
)
from .downloader import RetryConfig, estimate_cost, sync_transcripts
from .index_generator import (
    generate_index_markdown,
    get_downloaded_episodes,
    save_index,
    update_episode_status,
)
from .logging_config import ProgressLogger, configure_logging
from .rss_parser import (
    fetch_rss_feed,
    load_episodes,
    merge_episodes,
    parse_rss,
    save_episodes,
)
from .youtube_discovery import fetch_playlist_metadata, match_episodes


# Estimated average VTT file size (based on typical transcript length)
ESTIMATED_VTT_SIZE_KB = 100


def check_disk_space(num_files: int) -> tuple:
    """Check if there's enough disk space for downloads."""
    required_kb = num_files * ESTIMATED_VTT_SIZE_KB
    required_mb = required_kb // 1024
    try:
        disk_usage = shutil.disk_usage(TRANSCRIPTS_DIR.parent)
        available_mb = disk_usage.free // (1024 * 1024)
        has_space = available_mb >= required_mb
    except OSError:
        return True, required_mb, 0
    return has_space, required_mb, available_mb


# --- Pipeline Stage 1: Catalog ---


def cmd_catalog(args):
    """Stage 1: Fetch episode metadata from RSS and match YouTube links."""
    logger = configure_logging(
        verbose=args.verbose,
        log_file=LOGS_DIR / f"catalog_{datetime.now():%Y%m%d_%H%M%S}.log",
    )

    print("\n📋 Stage 1: Catalog\n")

    existing = load_episodes(EPISODES_JSON)
    existing_count = len(existing)

    # RSS fetch
    if not args.youtube_only:
        print("Fetching RSS feed...")
        try:
            rss_content = fetch_rss_feed()
        except Exception as e:
            logger.error("Failed to fetch RSS feed: %s", e)
            return 1
        new_episodes = parse_rss(rss_content)
        merged = merge_episodes(existing, new_episodes)
        new_count = len(merged) - existing_count
        print(f"  Episodes: {len(merged)} ({'+' + str(new_count) if new_count > 0 else 'no new'})")
    else:
        merged = existing

    # YouTube matching
    if not args.rss_only:
        print("Matching YouTube playlist...")
        playlist_url = args.playlist or YOUTUBE_PLAYLIST_URL
        try:
            youtube_videos = fetch_playlist_metadata(playlist_url)
        except RuntimeError as e:
            logger.error("Failed to fetch playlist: %s", e)
            print(f"  YouTube matching failed: {e}")
            # Save RSS results even if YouTube fails
            save_episodes(merged, EPISODES_JSON)
            return 1
        merged, stats = match_episodes(merged, youtube_videos)
        yt_with_link = sum(1 for ep in merged if ep.get("youtube_link"))
        print(f"  YouTube links: {yt_with_link} ({stats['newly_updated']} new)")

    # Save and regenerate index
    save_episodes(merged, EPISODES_JSON)
    downloaded, pending, no_link = update_episode_status(merged, TRANSCRIPTS_DIR)
    index_content = generate_index_markdown(merged)
    save_index(index_content, EPISODE_INDEX)

    print(f"\n  Total: {len(merged)} episodes")
    return 0


# --- Pipeline Stage 2: Transcribe ---


def cmd_transcribe(args):
    """Stage 2: Get transcripts (YouTube captions or Whisper fallback)."""
    logger = configure_logging(
        verbose=args.verbose,
        log_file=LOGS_DIR / f"transcribe_{datetime.now():%Y%m%d_%H%M%S}.log",
    )

    episodes = load_episodes(EPISODES_JSON)
    if not episodes:
        print("No episodes found. Run 'naruhodo catalog' first.")
        return 1

    # Update status to find what needs transcription
    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)

    source = args.source

    # Determine what to transcribe
    youtube_episodes = []
    whisper_episodes = []

    for ep in episodes:
        if ep.get("status") == "✅ Downloaded":
            continue

        if args.episode and ep.get("episode_number") != args.episode:
            continue

        if source in ("auto", "youtube") and ep.get("youtube_link") and ep.get("status") == "⬜ Pending":
            youtube_episodes.append(ep)
        elif source in ("auto", "whisper") and ep.get("audio_url"):
            # Only Whisper for episodes without YouTube link, or if source=whisper
            if source == "whisper" or not ep.get("youtube_link"):
                whisper_episodes.append(ep)

    if args.limit > 0:
        youtube_episodes = youtube_episodes[:args.limit]
        remaining = max(0, args.limit - len(youtube_episodes))
        whisper_episodes = whisper_episodes[:remaining]

    total = len(youtube_episodes) + len(whisper_episodes)

    if total == 0:
        print("\n✅ All episodes have transcripts.")
        print(f"   Total: {downloaded}")
        return 0

    # Show plan
    print(f"\n🎯 Stage 2: Transcribe\n")
    if youtube_episodes:
        print(f"  YouTube captions: {len(youtube_episodes)} episodes")
    if whisper_episodes:
        from . import whisper as wh
        audio_secs = wh.estimate_duration(whisper_episodes)
        print(f"  Whisper (local):  {len(whisper_episodes)} episodes (~{wh.format_duration(audio_secs)} audio)")
    print(f"  Total:            {total} episodes")

    if args.dry_run:
        print("\nEpisodes:")
        for ep in youtube_episodes:
            print(f"  #{ep.get('episode_number', '?'):>4} [YouTube] {ep['title'][:55]}")
        for ep in whisper_episodes:
            print(f"  #{ep.get('episode_number', '?'):>4} [Whisper] {ep['title'][:55]}")
        return 0

    # Confirmation
    if not args.yes:
        if not sys.stdin.isatty():
            print("⚠️  Non-interactive mode. Use --yes to proceed.")
            return 1
        try:
            response = input("\nProceed? [y/N]: ")
            if response.lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 0

    results = {"youtube_ok": 0, "whisper_ok": 0, "failed": 0, "flagged": 0}

    # YouTube captions
    if youtube_episodes:
        print(f"\nDownloading YouTube captions...")
        yt_results = sync_transcripts(youtube_episodes, TRANSCRIPTS_DIR)
        results["youtube_ok"] = yt_results["downloaded"]
        results["failed"] += yt_results["failed"]

    # Whisper transcription
    if whisper_episodes:
        try:
            from . import whisper as wh
        except ImportError:
            print("Error: MLX Whisper not installed (requires Apple Silicon).")
            print("Install with: uv sync --extra whisper")
            return 1

        AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        print(f"\nTranscribing with Whisper ({args.model})...")
        for i, ep in enumerate(whisper_episodes, 1):
            ep_num = ep.get("episode_number", "?")
            title = ep.get("title", "Unknown")
            audio_url = ep["audio_url"]
            output_filename = wh.get_output_filename(ep)
            output_path = TRANSCRIPTS_DIR / output_filename

            print(f"  [{i}/{len(whisper_episodes)}] #{ep_num}: {title[:50]}")

            if output_path.exists():
                results["whisper_ok"] += 1
                continue

            audio_path = AUDIO_CACHE_DIR / f"naruhodo_{ep_num}.mp3"
            if not audio_path.exists():
                if not wh.download_audio(audio_url, audio_path):
                    results["failed"] += 1
                    continue

            try:
                result = wh.transcribe(audio_path, model=args.model)
                wh.save_transcript_markdown(output_path, audio_path, result, args.model)
                results["whisper_ok"] += 1

                # Check quality flags
                quality = result.get("quality", {})
                if quality.get("mean_logprob", 0) < -0.8 or quality.get("repeated_6grams", 0) > 5:
                    results["flagged"] += 1
                    print(f"    ⚠️  Flagged: low confidence or repetition")

            except Exception as e:
                print(f"    Failed: {e}")
                results["failed"] += 1

            if not args.keep_audio and audio_path.exists():
                audio_path.unlink()

    # Update status and save
    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)
    save_episodes(episodes, EPISODES_JSON)
    index_content = generate_index_markdown(episodes)
    save_index(index_content, EPISODE_INDEX)

    # Report
    total_ok = results["youtube_ok"] + results["whisper_ok"]
    print(f"\n{'='*50}")
    print(f"Transcribe complete: {total_ok} done, {results['failed']} failed")
    if results["youtube_ok"]:
        print(f"  YouTube: {results['youtube_ok']}")
    if results["whisper_ok"]:
        print(f"  Whisper: {results['whisper_ok']}")
    if results["flagged"]:
        print(f"  ⚠️  {results['flagged']} flagged (review with 'naruhodo status')")

    return 0 if results["failed"] == 0 else 1


# --- Pipeline Stage 3: Diarize ---


def cmd_diarize(args):
    """Stage 3: Add speaker labels to existing transcripts."""
    configure_logging(verbose=args.verbose)

    from .diarization import (
        add_diarization_to_transcript,
        load_diarization_pipeline,
        parse_vtt_to_segments,
    )

    # Load pipeline
    print("Loading diarization pipeline...")
    pipeline = load_diarization_pipeline()
    if pipeline is None:
        print("Error: could not load diarization pipeline.")
        print("Install: uv sync --extra diarize")
        print("Set HF_TOKEN env var (see docs/diarization-setup.md).")
        return 1
    print("Diarization pipeline ready.\n")

    episodes = load_episodes(EPISODES_JSON)

    # Find transcripts needing diarization
    to_diarize = []
    for ep in episodes:
        if args.episode and ep.get("episode_number") != args.episode:
            continue
        if "REPLAY" in ep.get("title", "") or "REPOST" in ep.get("title", ""):
            continue

        ep_num = ep.get("episode_number", "")
        if not ep_num:
            continue

        # Check for existing transcript (whisper.md or vtt)
        transcript_path = _find_transcript(ep_num, ep.get("title", ""))
        if not transcript_path:
            continue

        # Check if already diarized (has **Speaker:** lines)
        if not args.force:
            content = transcript_path.read_text(encoding="utf-8")
            if "**Ken Fujioka:**" in content or "**Altay de Souza:**" in content:
                continue

        # Check if audio is available
        if not ep.get("audio_url"):
            continue

        to_diarize.append((ep, transcript_path))

    if not to_diarize:
        print("✅ All transcripts are diarized (or no transcripts found).")
        return 0

    if args.limit > 0:
        to_diarize = to_diarize[:args.limit]

    print(f"🗣️  Stage 3: Diarize\n")
    print(f"  Episodes to diarize: {len(to_diarize)}")

    if args.dry_run:
        for ep, path in to_diarize:
            fmt = "whisper" if path.suffix == ".md" else "vtt"
            print(f"  #{ep.get('episode_number', '?'):>4} [{fmt}] {ep['title'][:55]}")
        return 0

    if not args.yes:
        if not sys.stdin.isatty():
            print("⚠️  Non-interactive mode. Use --yes to proceed.")
            return 1
        try:
            response = input("\nProceed? [y/N]: ")
            if response.lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 0

    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    from . import whisper as wh

    results = {"ok": 0, "failed": 0, "flagged": 0}

    for i, (ep, transcript_path) in enumerate(to_diarize, 1):
        ep_num = ep.get("episode_number", "?")
        ep_type = ep.get("episode_type", "regular")
        guest = ep.get("guest", "")
        title = ep.get("title", "Unknown")

        label = f"({ep_type})" if not guest else f"({ep_type}, guest: {guest})"
        print(f"[{i}/{len(to_diarize)}] #{ep_num}: {title[:50]} {label}")

        # Download audio
        audio_path = AUDIO_CACHE_DIR / f"naruhodo_{ep_num}.mp3"
        if not audio_path.exists():
            print(f"    Downloading audio...")
            if not wh.download_audio(ep["audio_url"], audio_path):
                results["failed"] += 1
                continue

        # Get segments for alignment
        if transcript_path.name.endswith(".whisper.md"):
            segments_path = transcript_path.with_suffix(".segments.json")
            if segments_path.exists():
                import json
                segments = json.loads(segments_path.read_text())
            else:
                print(f"    No segments sidecar. Re-transcribe with 'naruhodo transcribe --source whisper --episode {ep_num}'")
                results["failed"] += 1
                if not args.keep_audio and audio_path.exists():
                    audio_path.unlink()
                continue
        else:
            # VTT: parse timestamps into segments
            segments = parse_vtt_to_segments(transcript_path)

        # Diarize
        t0 = time.monotonic()
        try:
            mapping = add_diarization_to_transcript(
                transcript_path, audio_path, pipeline,
                whisper_segments=segments,
                llm_spec=args.llm,
                episode_type=ep_type,
                guest_name=guest,
            )
            elapsed = time.monotonic() - t0
            confidence = mapping.get("confidence", "?")
            speaker_names = [n for n in mapping.get("mapping", {}).values() if n]
            print(f"    Speakers: {' & '.join(speaker_names)} (confidence: {confidence}, {elapsed:.0f}s)")
            results["ok"] += 1

            # Flag low-quality diarization
            # (Check by re-reading the file for segment count)
            content = transcript_path.read_text(encoding="utf-8")
            import re
            turns = len(re.findall(r"\*\*(Ken Fujioka|Altay de Souza):\*\*", content))
            if turns < 10:
                results["flagged"] += 1
                print(f"    ⚠️  Flagged: only {turns} speaker turns")

        except Exception as e:
            print(f"    Failed: {e}")
            results["failed"] += 1

        if not args.keep_audio and audio_path.exists():
            audio_path.unlink()

    # Report
    print(f"\n{'='*50}")
    print(f"Diarize complete: {results['ok']} done, {results['failed']} failed")
    if results["flagged"]:
        print(f"  ⚠️  {results['flagged']} flagged (low turn count, review with 'naruhodo status')")

    return 0 if results["failed"] == 0 else 1


def _find_transcript(ep_num: str, title: str):
    """Find a transcript file for an episode (whisper.md or vtt)."""
    if not TRANSCRIPTS_DIR.exists():
        return None

    # Prefer whisper.md (higher quality)
    for f in TRANSCRIPTS_DIR.iterdir():
        if f.name.endswith(".whisper.md") and f"#{ep_num} " in f.name:
            return f

    # Fall back to VTT
    for f in TRANSCRIPTS_DIR.iterdir():
        if f.suffix == ".vtt" and f"#{ep_num} " in f.name:
            return f

    return None


# --- Status Dashboard ---


def cmd_status(args):
    """Show pipeline state and quality summary."""
    configure_logging(verbose=args.verbose)

    episodes = load_episodes(EPISODES_JSON)
    if not episodes:
        print("No episodes found. Run 'naruhodo catalog' first.")
        return 1

    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)

    # Count transcript types
    vtt_count = 0
    whisper_count = 0
    diarized_count = 0
    if TRANSCRIPTS_DIR.exists():
        for f in TRANSCRIPTS_DIR.iterdir():
            if f.suffix == ".vtt":
                vtt_count += 1
            elif f.name.endswith(".whisper.md"):
                whisper_count += 1
                content = f.read_text(encoding="utf-8")
                if "**Ken Fujioka:**" in content or "**Altay de Souza:**" in content:
                    diarized_count += 1

    # Count quality flags
    flagged_transcribe = 0
    flagged_diarize = 0
    import json
    import re
    for f in TRANSCRIPTS_DIR.iterdir() if TRANSCRIPTS_DIR.exists() else []:
        if f.name.endswith(".quality.json"):
            try:
                data = json.loads(f.read_text())
                m = data.get("metrics", {})
                if m.get("mean_logprob", 0) < -0.8 or m.get("repeated_6grams", 0) > 5:
                    flagged_transcribe += 1
            except Exception:
                pass
        elif f.name.endswith(".whisper.md"):
            content = f.read_text(encoding="utf-8")
            if "**Ken Fujioka:**" in content or "**Altay de Souza:**" in content:
                turns = len(re.findall(r"\*\*(Ken Fujioka|Altay de Souza):\*\*", content))
                # Get duration from header
                dur_match = re.search(r"\*\*Duration:\*\* (\d+):(\d+)", content)
                if dur_match:
                    duration_min = int(dur_match.group(1)) + int(dur_match.group(2)) / 60
                    if turns < 10 and duration_min > 15:
                        flagged_diarize += 1

    with_transcript = vtt_count + whisper_count
    without = len(episodes) - downloaded

    print(f"\n📊 Naruhodo Pipeline Status\n")
    print(f"  Catalog:     {len(episodes)} episodes")

    yt_linked = sum(1 for ep in episodes if ep.get("youtube_link"))
    print(f"               {yt_linked} with YouTube link, {len(episodes) - yt_linked} without\n")

    print(f"  Transcribe:  {downloaded}/{len(episodes)} with transcript")
    if vtt_count or whisper_count:
        print(f"               {vtt_count} YouTube VTT, {whisper_count} Whisper")
    if without > 0:
        print(f"               {without} missing")
    if flagged_transcribe:
        print(f"               ⚠️  {flagged_transcribe} flagged (low confidence)")

    print(f"\n  Diarize:     {diarized_count}/{whisper_count} Whisper transcripts with speaker labels")
    if flagged_diarize:
        print(f"               ⚠️  {flagged_diarize} flagged (low turn count)")

    # Hints
    if without > 0:
        print(f"\n  Next: naruhodo transcribe")
    elif whisper_count > diarized_count:
        print(f"\n  Next: naruhodo diarize")
    elif flagged_transcribe or flagged_diarize:
        print(f"\n  Next: review flagged episodes")
    else:
        print(f"\n  ✅ Pipeline complete")

    return 0


# --- Deprecated command aliases ---


def _deprecated(new_cmd):
    """Create a wrapper that warns about deprecated command name."""
    def decorator(func):
        def wrapper(args):
            print(f"⚠️  Deprecated. Use 'naruhodo {new_cmd}' instead.\n")
            return func(args)
        return wrapper
    return decorator


def cmd_refresh_index(args):
    """Deprecated: use 'catalog --rss-only'."""
    args.youtube_only = False
    args.rss_only = False
    args.playlist = None
    return cmd_catalog(args)


def cmd_discover_youtube(args):
    """Deprecated: use 'catalog --youtube-only'."""
    args.youtube_only = False
    args.rss_only = False
    return cmd_catalog(args)


def cmd_sync(args):
    """Deprecated: use 'transcribe --source youtube'."""
    args.source = "youtube"
    args.episode = None
    args.limit = 0
    args.model = "large-v3"
    args.dry_run = False
    args.keep_audio = False
    return cmd_transcribe(args)


def cmd_whisper(args):
    """Deprecated: use 'transcribe --source whisper' + 'diarize'."""
    args.source = "whisper"
    return cmd_transcribe(args)


def ensure_directories():
    """Create required directories if they don't exist."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def main():
    """Main entry point."""
    ensure_directories()

    parser = argparse.ArgumentParser(
        prog="naruhodo",
        description="Naruhodo podcast transcript pipeline",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Pipeline stages")

    # --- Pipeline commands ---

    # catalog
    cat_parser = subparsers.add_parser("catalog", help="Fetch episode metadata (RSS + YouTube)")
    cat_parser.add_argument("--rss-only", action="store_true", help="Skip YouTube matching")
    cat_parser.add_argument("--youtube-only", action="store_true", help="Skip RSS refresh")
    cat_parser.add_argument("--playlist", type=str, help="Custom YouTube playlist URL")
    cat_parser.set_defaults(func=cmd_catalog)

    # transcribe
    tr_parser = subparsers.add_parser("transcribe", help="Get transcripts (YouTube or Whisper)")
    tr_parser.add_argument("--source", choices=["auto", "youtube", "whisper"], default="auto",
                           help="Transcript source (default: auto)")
    tr_parser.add_argument("--episode", type=str, help="Specific episode number")
    tr_parser.add_argument("--limit", type=int, default=0, help="Max episodes (0=all)")
    tr_parser.add_argument("--model", type=str, default="large-v3", help="Whisper model")
    tr_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    tr_parser.add_argument("--dry-run", action="store_true", help="Show plan without running")
    tr_parser.add_argument("--keep-audio", action="store_true", help="Keep downloaded audio")
    tr_parser.set_defaults(func=cmd_transcribe)

    # diarize
    di_parser = subparsers.add_parser("diarize", help="Add speaker labels to transcripts")
    di_parser.add_argument("--episode", type=str, help="Specific episode number")
    di_parser.add_argument("--limit", type=int, default=0, help="Max episodes (0=all)")
    di_parser.add_argument("--llm", type=str, default="ollama:qwen2.5:72b-instruct-q4_K_M",
                           help="LLM for speaker ID (e.g., claude:sonnet)")
    di_parser.add_argument("-y", "--yes", action="store_true", help="Skip confirmation")
    di_parser.add_argument("--dry-run", action="store_true", help="Show plan without running")
    di_parser.add_argument("--keep-audio", action="store_true", help="Keep downloaded audio")
    di_parser.add_argument("--force", action="store_true", help="Re-diarize already labeled transcripts")
    di_parser.set_defaults(func=cmd_diarize)

    # status
    st_parser = subparsers.add_parser("status", help="Show pipeline state")
    st_parser.set_defaults(func=cmd_status)

    # --- Deprecated aliases ---

    dep_refresh = subparsers.add_parser("refresh-index", help="(deprecated: use catalog)")
    dep_refresh.set_defaults(func=_deprecated("catalog")(cmd_refresh_index))

    dep_discover = subparsers.add_parser("discover-youtube", help="(deprecated: use catalog)")
    dep_discover.add_argument("--playlist", type=str)
    dep_discover.set_defaults(func=_deprecated("catalog")(cmd_discover_youtube))

    dep_sync = subparsers.add_parser("sync", help="(deprecated: use transcribe)")
    dep_sync.add_argument("-y", "--yes", action="store_true")
    dep_sync.set_defaults(func=_deprecated("transcribe")(cmd_sync))

    dep_whisper = subparsers.add_parser("whisper", help="(deprecated: use transcribe + diarize)")
    dep_whisper.add_argument("--limit", type=int, default=0)
    dep_whisper.add_argument("--episode", type=str)
    dep_whisper.add_argument("--model", type=str, default="large-v3")
    dep_whisper.add_argument("--no-diarize", action="store_true")
    dep_whisper.add_argument("--llm", type=str, default="ollama:qwen2.5:72b-instruct-q4_K_M")
    dep_whisper.add_argument("-y", "--yes", action="store_true")
    dep_whisper.add_argument("--dry-run", action="store_true")
    dep_whisper.add_argument("--keep-audio", action="store_true")
    dep_whisper.set_defaults(func=_deprecated("transcribe + diarize")(cmd_whisper))

    dep_qc = subparsers.add_parser("quality-check", help="(deprecated: use status)")
    dep_qc.add_argument("--tier", type=int, choices=[1, 2, 3, 4])
    dep_qc.add_argument("--cross-validate", action="store_true")
    dep_qc.add_argument("--llm-check", type=int, metavar="N")
    dep_qc.add_argument("--llm", type=str, default="claude:sonnet")
    dep_qc.add_argument("--episode", type=str)
    dep_qc.add_argument("--json", action="store_true")
    dep_qc.set_defaults(func=_deprecated("status")(lambda args: __import__('src.quality', fromlist=['run_quality_check']).run_quality_check(
        tier=args.tier, cross_validate=args.cross_validate,
        llm_check=args.llm_check or 0, llm_spec=args.llm,
        episode=args.episode, as_json=args.json,
    )))

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
