#!/usr/bin/env python3
"""CLI for Naruhodo podcast transcript downloader."""

import argparse
import shutil
import sys
from datetime import datetime

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


def main():
    """Main entry point."""
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
        help="Download pending transcripts",
    )
    sync_parser.add_argument(
        "-y", "--yes",
        action="store_true",
        help="Skip confirmation prompt",
    )
    sync_parser.set_defaults(func=cmd_sync)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
