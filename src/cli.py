#!/usr/bin/env python3
"""CLI for Naruhodo podcast transcript downloader."""

import argparse
import functools
import shutil
import sys
import time
from datetime import datetime

# Ensure print output is visible immediately when piped (e.g., tee, CI logs)
print = functools.partial(print, flush=True)

from .config import (
    DATA_DIR,
    EPISODE_INDEX,
    EPISODES_JSON,
    LOGS_DIR,
    TRANSCRIPTS_DIR,
    YOUTUBE_PLAYLIST_URL,
)
from .downloader import estimate_cost, sync_transcripts, RetryConfig
from .index_generator import (
    generate_index_markdown,
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
from .youtube_discovery import (
    fetch_playlist_metadata,
    match_episodes,
)

# Estimated average VTT file size (based on typical transcript length)
ESTIMATED_VTT_SIZE_KB = 100  # ~100KB per transcript file


def check_disk_space(num_files: int) -> tuple[bool, int, int]:
    """Check if there's enough disk space for downloads.

    Args:
        num_files: Number of files to download

    Returns:
        Tuple of (has_space, required_mb, available_mb)
    """
    required_kb = num_files * ESTIMATED_VTT_SIZE_KB
    required_mb = required_kb // 1024

    try:
        disk_usage = shutil.disk_usage(TRANSCRIPTS_DIR.parent)
        available_mb = disk_usage.free // (1024 * 1024)
        has_space = available_mb >= required_mb
    except OSError:
        # If we can't check, assume we have space
        return True, required_mb, 0

    return has_space, required_mb, available_mb


def print_banner():
    """Print the application banner."""
    print("\n📊 Naruhodo Transcript Sync\n")


def cmd_status(args):
    """Show current sync status."""
    logger = configure_logging(verbose=args.verbose)

    # Load episodes
    episodes = load_episodes(EPISODES_JSON)
    if not episodes:
        print("No episodes found. Run 'refresh-index' first to fetch from RSS.")
        return 1

    # Update status based on downloaded files
    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)

    print_banner()
    print("Current status:")
    print(f"  ├─ Episodes in metadata:       {len(episodes)}")
    print(f"  ├─ Transcripts downloaded:     {downloaded}")
    print(f"  ├─ Pending downloads:          {pending}")
    print(f"  └─ Missing YouTube link:       {no_link}")

    if no_link > 0:
        print(f"\n⚠️  {no_link} episodes are missing YouTube links.")
        print("    Run 'discover-youtube' to try matching them from the playlist.")
        print("    Or run 'whisper' to transcribe locally from podcast audio.")

    if pending > 0:
        cost = estimate_cost(pending)
        print("\nEstimated cost for full sync:")
        print(f"  ├─ YouTube API requests:     {cost['requests']}")
        print(f"  ├─ Download time:            ~{cost['download_minutes']} minutes")
        print(f"  ├─ Expected rate limits:     ~{cost['rate_limits']}")
        print(f"  ├─ Rate limit wait time:     ~{cost['wait_hours']} hours")
        print(f"  └─ Total estimated time:     {cost['total_hours']} hours")

    return 0


def cmd_refresh_index(args):
    """Refresh episode metadata from RSS feed."""
    logger = configure_logging(
        verbose=args.verbose,
        log_file=LOGS_DIR / f"refresh_{datetime.now():%Y%m%d_%H%M%S}.log",
    )

    print_banner()
    print("Refreshing episode metadata from RSS feed...")

    # Fetch and parse RSS
    try:
        rss_content = fetch_rss_feed()
    except Exception as e:
        logger.error("Failed to fetch RSS feed: %s", e)
        return 1

    new_episodes = parse_rss(rss_content)
    logger.info("Parsed %d episodes from RSS", len(new_episodes))

    # Merge with existing data
    existing = load_episodes(EPISODES_JSON)
    merged = merge_episodes(existing, new_episodes)

    # Update status
    downloaded, pending, no_link = update_episode_status(merged, TRANSCRIPTS_DIR)

    # Save updated data
    save_episodes(merged, EPISODES_JSON)
    logger.info("Saved %d episodes to %s", len(merged), EPISODES_JSON)

    # Generate index
    index_content = generate_index_markdown(merged, downloaded, pending, no_link)
    save_index(index_content, EPISODE_INDEX)

    print(f"\n✅ Updated {len(merged)} episodes")
    print(f"   Downloaded: {downloaded}")
    print(f"   Pending: {pending}")
    print(f"   Missing YouTube link: {no_link}")

    return 0


def cmd_discover_youtube(args):
    """Discover YouTube links by matching playlist videos to RSS episodes."""
    logger = configure_logging(
        verbose=args.verbose,
        log_file=LOGS_DIR / f"discover_{datetime.now():%Y%m%d_%H%M%S}.log",
    )

    # Load episodes
    episodes = load_episodes(EPISODES_JSON)
    if not episodes:
        print("No episodes found. Run 'refresh-index' first to fetch from RSS.")
        return 1

    print_banner()
    print("Discovering YouTube links from playlist...")

    # Fetch playlist metadata
    playlist_url = args.playlist or YOUTUBE_PLAYLIST_URL
    try:
        youtube_videos = fetch_playlist_metadata(playlist_url)
    except RuntimeError as e:
        logger.error("Failed to fetch playlist: %s", e)
        print(f"\n❌ Failed to fetch playlist: {e}")
        return 1

    # Match episodes to YouTube videos
    episodes, stats = match_episodes(episodes, youtube_videos)

    # Save updated episodes
    save_episodes(episodes, EPISODES_JSON)
    logger.info("Saved %d episodes to %s", len(episodes), EPISODES_JSON)

    # Regenerate index with updated links
    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)
    index_content = generate_index_markdown(episodes, downloaded, pending, no_link)
    save_index(index_content, EPISODE_INDEX)

    # Print summary
    print(f"\n✅ YouTube discovery complete")
    print(f"\nSummary:")
    print(f"  ├─ RSS episodes:              {stats['total_rss_episodes']}")
    print(f"  ├─ YouTube videos:            {stats['total_youtube_videos']}")
    print(f"  ├─ Matched:                   {stats['matched']}")
    print(f"  ├─ Already had link:          {stats['already_had_link']}")
    print(f"  ├─ Newly updated:             {stats['newly_updated']}")
    print(f"  ├─ RSS unmatched:             {stats['rss_unmatched']}")
    print(f"  └─ YouTube unmatched:         {stats['youtube_unmatched']}")

    if args.verbose and stats['rss_unmatched_keys']:
        print(f"\nRSS episodes without YouTube match:")
        for key in stats['rss_unmatched_keys'][:20]:
            print(f"    {key}")
        if len(stats['rss_unmatched_keys']) > 20:
            print(f"    ... and {len(stats['rss_unmatched_keys']) - 20} more")

    if args.verbose and stats['youtube_unmatched_keys']:
        print(f"\nYouTube videos without RSS match:")
        for key in stats['youtube_unmatched_keys'][:20]:
            print(f"    {key}")
        if len(stats['youtube_unmatched_keys']) > 20:
            print(f"    ... and {len(stats['youtube_unmatched_keys']) - 20} more")

    return 0


def cmd_sync(args):
    """Sync transcripts - download new episodes."""
    logger = configure_logging(
        verbose=args.verbose,
        log_file=LOGS_DIR / f"sync_{datetime.now():%Y%m%d_%H%M%S}.log",
    )

    # Load episodes
    episodes = load_episodes(EPISODES_JSON)
    if not episodes:
        print("No episodes found. Run 'refresh-index' first.")
        return 1

    # Update status
    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)

    # Filter to pending episodes with YouTube links
    pending_episodes = [
        ep for ep in episodes
        if ep.get("status") == "⬜ Pending" and ep.get("youtube_link")
    ]

    if not pending_episodes:
        print("\n✅ All episodes with YouTube links are already downloaded.")
        print(f"   Total downloaded: {downloaded}")
        print(f"   Missing YouTube link: {no_link}")
        return 0

    # Show cost estimate
    print_banner()
    print("Current status:")
    print(f"  ├─ Episodes in metadata:       {len(episodes)}")
    print(f"  ├─ Transcripts downloaded:     {downloaded}")
    print(f"  └─ Pending with YouTube link:  {len(pending_episodes)}")

    cost = estimate_cost(len(pending_episodes))
    print("\nEstimated cost:")
    print(f"  ├─ YouTube API requests:     {cost['requests']}")
    print(f"  ├─ Download time:            ~{cost['download_minutes']} minutes (at 3s/request)")
    print(f"  ├─ Expected rate limits:     ~{cost['rate_limits']} (every ~60 requests)")
    print(f"  ├─ Rate limit wait time:     ~{cost['wait_hours']} hours (1h per limit)")
    print(f"  └─ Total estimated time:     {cost['total_hours']} hours")

    print("\n⚠️  YouTube may rate-limit after ~60 requests.")
    print("    The script will automatically retry with exponential backoff.")
    print("    You can safely Ctrl+C and resume later - progress is saved.")

    # Check disk space
    has_space, required_mb, available_mb = check_disk_space(len(pending_episodes))
    if not has_space:
        print(f"\n⚠️  Low disk space warning:")
        print(f"    Required:  ~{required_mb} MB")
        print(f"    Available: ~{available_mb} MB")
        print("    Downloads may fail if disk fills up.")

    # Ask for confirmation unless --yes
    if not args.yes:
        if not sys.stdin.isatty():
            print("\n⚠️  Running in non-interactive mode. Use --yes (-y) to proceed.")
            return 1
        try:
            response = input("\nProceed? [y/N]: ")
            if response.lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 0

    # Create progress logger
    progress = ProgressLogger(
        logger=logger,
        total=len(pending_episodes),
        task="Download",
        min_interval=20.0,
    )

    # Configure retry behavior
    retry_config = RetryConfig(
        max_retries=5,
        initial_delay=60.0,
        backoff_factor=2.0,
        max_delay=3600.0,
        rate_limit_delay=3600.0,
    )

    # Start sync
    print(f"\nStarting download of {len(pending_episodes)} episodes...")
    progress.update(0, force=True)

    try:
        results = sync_transcripts(
            episodes=pending_episodes,
            output_dir=TRANSCRIPTS_DIR,
            progress_logger=progress,
            retry_config=retry_config,
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Download interrupted. Progress has been saved.")
        print("    Run 'sync' again to resume.")
        return 1

    # Update status and save
    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)
    save_episodes(episodes, EPISODES_JSON)

    # Regenerate index
    index_content = generate_index_markdown(episodes, downloaded, pending, no_link)
    save_index(index_content, EPISODE_INDEX)

    # Print summary
    print(f"\n✅ Sync complete")
    print(f"   Downloaded: {results['downloaded']}")
    print(f"   Skipped (no link): {results['skipped']}")
    print(f"   No subtitles: {results['no_subtitles']}")
    print(f"   Failed: {results['failed']}")

    if results["errors"]:
        print("\n   Errors:")
        for err in results["errors"][:10]:
            print(f"     - {err['video_id']}: {err['error']}")
        if len(results["errors"]) > 10:
            print(f"     ... and {len(results['errors']) - 10} more")

    return 0


def cmd_whisper(args):
    """Transcribe episodes locally using MLX Whisper."""
    try:
        from . import whisper as wh
    except ImportError:
        print("Error: MLX Whisper not installed (requires Apple Silicon).")
        print("Install with: uv sync --extra whisper")
        return 1

    from .diarization import load_diarization_pipeline, add_diarization_to_transcript

    configure_logging(verbose=args.verbose)

    # Load diarization pipeline early if requested (fail fast)
    diarization_pipeline = None
    if not args.no_diarize:
        print("Loading diarization pipeline...")
        diarization_pipeline = load_diarization_pipeline()
        if diarization_pipeline is None:
            print("Error: could not load diarization pipeline.")
            print("Install: uv sync --extra diarize")
            print("Set HF_TOKEN env var (see README for setup steps).")
            print("Or use --no-diarize to skip speaker labels.")
            return 1
        print("Diarization pipeline ready.\n")

    # Find episodes to transcribe
    episodes = load_episodes(EPISODES_JSON)
    missing = wh.get_missing_episodes(episodes)

    if args.episode:
        missing = [ep for ep in missing if ep.get("episode_number") == args.episode]
        if not missing:
            all_eps = [ep for ep in episodes if ep.get("episode_number") == args.episode]
            if all_eps:
                print(f"Episode #{args.episode} already has a transcript.")
            else:
                print(f"Episode #{args.episode} not found.")
            return 0

    if args.limit > 0:
        missing = missing[:args.limit]

    if not missing:
        print("All episodes have transcripts!")
        return 0

    # Show plan
    total_audio = wh.estimate_duration(missing)
    est_time = total_audio * 0.3

    print_banner()
    print(f"  Episodes to transcribe:  {len(missing)}")
    print(f"  Total audio:             {wh.format_duration(total_audio)}")
    print(f"  Model:                   {args.model}")
    print(f"  Diarization:             {'yes (pyannote + Ollama)' if not args.no_diarize else 'no'}")
    print(f"  Est. transcription time: ~{wh.format_duration(est_time)}")
    print(f"  Est. download size:      ~{total_audio / 60:.0f} MB")
    print()

    if args.dry_run:
        print("Episodes that would be transcribed:")
        for ep in missing:
            print(f"  {ep.get('episode_number', '?'):>4}  {ep['title'][:70]}  ({ep.get('duration', '?')})")
        return 0

    # Ask for confirmation unless --yes
    if not args.yes:
        if not sys.stdin.isatty():
            print("⚠️  Running in non-interactive mode. Use --yes (-y) to proceed.")
            return 1
        try:
            response = input("Proceed? [y/N]: ")
            if response.lower() not in ("y", "yes"):
                print("Aborted.")
                return 0
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.")
            return 0

    # Create directories
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    from .config import AUDIO_CACHE_DIR
    AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Process episodes
    results = {"success": 0, "failed": 0, "diarized": 0, "errors": []}
    start_time = time.monotonic()

    for i, ep in enumerate(missing, 1):
        title = ep.get("title", "Unknown")
        ep_num = ep.get("episode_number", "?")
        audio_url = ep["audio_url"]
        output_filename = wh.get_output_filename(ep)
        output_path = TRANSCRIPTS_DIR / output_filename

        print(f"[{i}/{len(missing)}] #{ep_num}: {title[:60]}")

        if output_path.exists():
            print(f"    Skipping (already exists)")
            results["success"] += 1
            continue

        # Download audio
        audio_path = AUDIO_CACHE_DIR / f"naruhodo_{ep_num}.mp3"
        if not audio_path.exists():
            print(f"    Downloading audio...")
            if not wh.download_audio(audio_url, audio_path):
                results["failed"] += 1
                results["errors"].append({"episode": ep_num, "error": "Download failed"})
                continue

        audio_size_mb = audio_path.stat().st_size / (1024 * 1024)
        print(f"    Audio: {audio_size_mb:.1f} MB")

        # Transcribe
        print(f"    Transcribing with {args.model}...")
        t0 = time.monotonic()
        try:
            result = wh.transcribe(audio_path, model=args.model)
            wh.save_transcript_markdown(output_path, audio_path, result, args.model)
            elapsed = time.monotonic() - t0
            print(f"    Transcribed: {result['word_count']} words, took {wh.format_duration(elapsed)}")
            results["success"] += 1
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(f"    Failed: {e}")
            results["failed"] += 1
            results["errors"].append({"episode": ep_num, "error": str(e)[:200]})
            if not args.keep_audio and audio_path.exists():
                audio_path.unlink()
            continue

        # Diarize if requested
        if not args.no_diarize and diarization_pipeline and output_path.exists():
            ep_type = ep.get("episode_type", "regular")
            guest = ep.get("guest", "")
            speaker_label = f"({ep_type}, guest: {guest})" if guest else f"({ep_type})"
            print(f"    Diarizing {speaker_label}...")
            t1 = time.monotonic()
            try:
                mapping = add_diarization_to_transcript(
                    output_path, audio_path, diarization_pipeline,
                    whisper_segments=result.get("segments", []),
                    llm_spec=args.llm,
                    episode_type=ep_type,
                    guest_name=guest,
                )
                d_elapsed = time.monotonic() - t1
                speaker_names = [
                    mapping.get(f"SPEAKER_{i:02d}", "")
                    for i in range(2)
                ]
                speaker_names = [n for n in speaker_names if n]
                confidence = mapping.get("confidence", "?")
                print(f"    Speakers: {' & '.join(speaker_names)} (confidence: {confidence}, took {wh.format_duration(d_elapsed)})")
                results["diarized"] += 1
            except Exception as e:
                print(f"    Diarization failed: {e}")

        # Clean up audio
        if not args.keep_audio and audio_path.exists():
            audio_path.unlink()

    # Update status and save
    from .index_generator import generate_index_markdown, save_index, update_episode_status
    downloaded, pending, no_link = update_episode_status(episodes, TRANSCRIPTS_DIR)
    save_episodes(episodes, EPISODES_JSON)
    index_content = generate_index_markdown(episodes, downloaded, pending, no_link)
    save_index(index_content, EPISODE_INDEX)

    # Summary
    total_time = time.monotonic() - start_time
    print(f"\n{'='*50}")
    print(f"Transcription complete in {wh.format_duration(total_time)}")
    print(f"  Success:   {results['success']}")
    if not args.no_diarize:
        print(f"  Diarized:  {results['diarized']}")
    print(f"  Failed:    {results['failed']}")

    if results["errors"]:
        print(f"\nErrors:")
        for err in results["errors"][:10]:
            print(f"  #{err['episode']}: {err['error'][:80]}")

    return 0 if results["failed"] == 0 else 1


def cmd_quality_check(args):
    """Analyze transcript quality."""
    configure_logging(verbose=args.verbose)

    from .quality import run_quality_check
    return run_quality_check(
        tier=args.tier,
        cross_validate=args.cross_validate,
        llm_check=args.llm_check or 0,
        llm_spec=args.llm,
        episode=args.episode,
        as_json=args.json,
    )


def ensure_directories():
    """Create required directories if they don't exist."""
    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def main():
    """Main entry point."""
    # Ensure required directories exist
    ensure_directories()

    parser = argparse.ArgumentParser(
        prog="naruhodo",
        description="Download and manage Naruhodo podcast transcripts",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show current sync status",
    )
    status_parser.set_defaults(func=cmd_status)

    # refresh-index command
    refresh_parser = subparsers.add_parser(
        "refresh-index",
        help="Refresh episode metadata from RSS feed",
    )
    refresh_parser.set_defaults(func=cmd_refresh_index)

    # discover-youtube command
    discover_parser = subparsers.add_parser(
        "discover-youtube",
        help="Match YouTube playlist videos to RSS episodes",
    )
    discover_parser.add_argument(
        "--playlist",
        type=str,
        help="YouTube playlist URL (uses default Naruhodo playlist if not specified)",
    )
    discover_parser.set_defaults(func=cmd_discover_youtube)

    # sync command
    sync_parser = subparsers.add_parser(
        "sync",
        help="Download pending transcripts (YouTube auto-captions)",
    )
    sync_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    sync_parser.set_defaults(func=cmd_sync)

    # whisper command
    whisper_parser = subparsers.add_parser(
        "whisper",
        help="Transcribe locally with MLX Whisper (Apple Silicon)",
    )
    whisper_parser.add_argument(
        "--limit", type=int, default=0,
        help="Maximum number of episodes to transcribe (0 = all)",
    )
    whisper_parser.add_argument(
        "--episode", type=str,
        help="Transcribe a specific episode by number (e.g., 400)",
    )
    whisper_parser.add_argument(
        "--model", type=str, default="large-v3",
        help="Whisper model (default: large-v3)",
    )
    whisper_parser.add_argument(
        "--no-diarize", action="store_true",
        help="Skip speaker diarization",
    )
    whisper_parser.add_argument(
        "--llm", type=str, default="ollama:qwen2.5:72b-instruct-q4_K_M",
        help="LLM for speaker ID: ollama:model or claude:model (e.g., claude:sonnet)",
    )
    whisper_parser.add_argument(
        "-y", "--yes", action="store_true",
        help="Skip confirmation prompt",
    )
    whisper_parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be transcribed without doing it",
    )
    whisper_parser.add_argument(
        "--keep-audio", action="store_true",
        help="Keep downloaded audio files after transcription",
    )
    whisper_parser.set_defaults(func=cmd_whisper)

    # quality-check command
    quality_parser = subparsers.add_parser(
        "quality-check",
        help="Analyze transcript quality (multi-tier)",
    )
    quality_parser.add_argument(
        "--tier", type=int, choices=[1, 2, 3, 4],
        help="Run specific tier only (1=Whisper signals, 2=episode metrics, 3=cross-validate, 4=LLM)",
    )
    quality_parser.add_argument(
        "--cross-validate", action="store_true",
        help="Run Tier 3: VTT vs Whisper WER comparison",
    )
    quality_parser.add_argument(
        "--llm-check", type=int, metavar="N",
        help="Tier 4: LLM spot-check top N flagged episodes",
    )
    quality_parser.add_argument(
        "--llm", type=str, default="claude:sonnet",
        help="LLM for Tier 4 (e.g., claude:sonnet, ollama:qwen2.5:72b)",
    )
    quality_parser.add_argument(
        "--episode", type=str,
        help="Check a specific episode",
    )
    quality_parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON",
    )
    quality_parser.set_defaults(func=cmd_quality_check)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
