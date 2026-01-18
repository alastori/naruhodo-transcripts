"""Generate episode index and update download status."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("naruhodo")


def get_downloaded_episodes(transcripts_dir: Path) -> tuple[set[str], set[str]]:
    """Get set of downloaded episode identifiers from filenames.

    Args:
        transcripts_dir: Directory containing transcript files

    Returns:
        Tuple of (episode_numbers, normalized_titles)
    """
    downloaded_numbers = set()
    downloaded_titles = set()

    if not transcripts_dir.exists():
        return downloaded_numbers, downloaded_titles

    for filename in os.listdir(transcripts_dir):
        if not filename.endswith(".vtt"):
            continue

        # Extract regular episode number (Naruhodo #XXX)
        match = re.search(r"Naruhodo\s+#(\d+)", filename)
        if match:
            downloaded_numbers.add(f"N{match.group(1)}")

        # Extract interview episode number (Entrevista #XX)
        match = re.search(r"Entrevista\s+#(\d+)", filename)
        if match:
            downloaded_numbers.add(f"E{match.group(1)}")

        # Store normalized title for fallback matching
        title_match = re.match(r"\d+ - (.+)\.[a-z]{2}\.vtt$", filename)
        if title_match:
            title = title_match.group(1)
            title = title.replace("：", ":").replace("？", "?").replace("！", "!")
            downloaded_titles.add(title)

    return downloaded_numbers, downloaded_titles


def update_episode_status(
    episodes: list[dict],
    transcripts_dir: Path,
) -> tuple[int, int]:
    """Update episode download status based on existing files.

    Args:
        episodes: List of episode dictionaries
        transcripts_dir: Directory containing transcript files

    Returns:
        Tuple of (downloaded_count, pending_count)
    """
    downloaded_numbers, downloaded_titles = get_downloaded_episodes(transcripts_dir)

    logger.debug(
        "Found %d VTT files, %d unique episode identifiers",
        sum(1 for f in transcripts_dir.glob("*.vtt")) if transcripts_dir.exists() else 0,
        len(downloaded_numbers),
    )

    downloaded_count = 0
    pending_count = 0

    for ep in episodes:
        title = ep["title"]
        ep_num = ep.get("episode_number", "")

        is_downloaded = False

        # Check by episode number (most reliable)
        if "Entrevista" in title and ep_num:
            if f"E{ep_num}" in downloaded_numbers:
                is_downloaded = True
        elif ep_num:
            if f"N{ep_num}" in downloaded_numbers:
                is_downloaded = True

        # Fallback to title matching
        if not is_downloaded:
            normalized_title = title.replace(":", "：").replace("?", "？").replace("!", "！")
            if title in downloaded_titles or normalized_title in downloaded_titles:
                is_downloaded = True
            else:
                # Partial match on episode identifier
                title_parts = title.split(" - ")
                if len(title_parts) > 1:
                    ep_identifier = title_parts[0]
                    for dt in downloaded_titles:
                        if ep_identifier.replace(":", "：") in dt or ep_identifier in dt:
                            is_downloaded = True
                            break

        if is_downloaded:
            ep["status"] = "✅ Downloaded"
            downloaded_count += 1
        else:
            ep["status"] = "⬜ Pending"
            pending_count += 1

    return downloaded_count, pending_count


def generate_index_markdown(
    episodes: list[dict],
    downloaded_count: int,
    pending_count: int,
) -> str:
    """Generate markdown index content.

    Args:
        episodes: List of episode dictionaries
        downloaded_count: Number of downloaded episodes
        pending_count: Number of pending episodes

    Returns:
        Markdown content as string
    """
    lines = [
        "# Naruhodo Podcast - Episode Index",
        "",
        f"Total episodes in RSS feed: {len(episodes)}",
        f"Transcripts downloaded: {downloaded_count}",
        f"Pending: {pending_count}",
        "",
        f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Episodes",
        "",
        "| # | Title | Date | Duration | Guest | Summary | References | Status |",
        "|---|-------|------|----------|-------|---------|------------|--------|",
    ]

    for ep in episodes:
        num = ep.get("episode_number", "")
        title = ep.get("title", "").replace("|", "\\|")
        date = ep.get("date", "")
        duration = ep.get("duration", "")
        guest = ep.get("guest", "").replace("|", "\\|")
        summary = ep.get("summary", "").replace("|", "\\|")
        status = ep.get("status", "⬜ Pending")

        # Format references as markdown links
        refs = ep.get("references", [])
        refs_md = format_references(refs)

        row = f"| {num} | {title} | {date} | {duration} | {guest} | {summary} | {refs_md} | {status} |"
        lines.append(row)

    return "\n".join(lines)


def format_references(refs: list[str], max_refs: int = 5) -> str:
    """Format reference URLs as markdown links.

    Args:
        refs: List of reference URLs
        max_refs: Maximum number of references to include

    Returns:
        Markdown formatted references
    """
    if not refs:
        return ""

    ref_links = []
    for i, ref in enumerate(refs[:max_refs]):
        # Create a short label based on domain
        if "lattes.cnpq" in ref:
            label = "Lattes"
        elif "doi.org" in ref or "pubmed" in ref.lower():
            label = f"Paper{i + 1}" if i > 0 else "Paper"
        elif "twitter.com" in ref or "x.com" in ref:
            label = "Twitter"
        elif "instagram.com" in ref:
            label = "Instagram"
        elif "youtube.com" in ref:
            label = "Video"
        elif "wikipedia" in ref:
            label = "Wiki"
        elif "teses.usp" in ref or "bdtd" in ref:
            label = "Tese"
        elif "scielo" in ref:
            label = "SciELO"
        else:
            label = f"Ref{i + 1}"

        ref_links.append(f"[{label}]({ref})")

    return " ".join(ref_links)


def save_index(content: str, path: Path):
    """Save index markdown to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    logger.info("Updated %s", path)
