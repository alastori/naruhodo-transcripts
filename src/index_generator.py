"""Generate episode index and update download status."""

import logging
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

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

    for f in transcripts_dir.iterdir():
        if f.suffix != ".vtt":
            continue
        filename = f.name

        # Extract regular episode number (Naruhodo #XXX)
        match = re.search(r"Naruhodo\s+#(\d+)", filename)
        if match:
            downloaded_numbers.add(f"N{match.group(1)}")

        # Extract interview episode number (Entrevista #XX)
        match = re.search(r"Entrevista\s+#(\d+)", filename)
        if match:
            downloaded_numbers.add(f"E{match.group(1)}")

        # Extract extra episode number (Extra #XX)
        match = re.search(r"Extra\s+#(\d+)", filename)
        if match:
            downloaded_numbers.add(f"X{match.group(1)}")

        # Store normalized title for fallback matching
        title_match = re.match(r"\d+ - (.+)\.[a-z]{2}\.vtt$", filename)
        if title_match:
            title = title_match.group(1)
            title = title.replace("\uff1a", ":").replace("\uff1f", "?").replace("\uff01", "!")
            downloaded_titles.add(title)

    return downloaded_numbers, downloaded_titles


def update_episode_status(
    episodes: list[dict],
    transcripts_dir: Path,
) -> tuple[int, int, int]:
    """Update episode download status based on existing files.

    Args:
        episodes: List of episode dictionaries
        transcripts_dir: Directory containing transcript files

    Returns:
        Tuple of (downloaded_count, pending_count, no_link_count)
    """
    downloaded_numbers, downloaded_titles = get_downloaded_episodes(transcripts_dir)

    logger.debug(
        "Found %d unique episode identifiers from VTT files",
        len(downloaded_numbers),
    )

    downloaded_count = 0
    pending_count = 0
    no_link_count = 0

    for ep in episodes:
        title = ep["title"]
        ep_num = ep.get("episode_number", "")

        is_downloaded = False

        # Check by episode number and type (most reliable)
        if "Entrevista" in title and ep_num:
            if f"E{ep_num}" in downloaded_numbers:
                is_downloaded = True
        elif "Extra" in title and ep_num:
            if f"X{ep_num}" in downloaded_numbers:
                is_downloaded = True
        elif ep_num:
            if f"N{ep_num}" in downloaded_numbers:
                is_downloaded = True

        # Fallback to title matching
        if not is_downloaded:
            normalized_title = title.replace(":", "\uff1a").replace("?", "\uff1f").replace("!", "\uff01")
            if title in downloaded_titles or normalized_title in downloaded_titles:
                is_downloaded = True
            else:
                # Partial match on episode identifier (e.g., "Naruhodo Extra")
                # Only for episodes without a number (to avoid #45 matching #450)
                title_parts = title.split(" - ")
                if len(title_parts) > 1 and not ep_num:
                    ep_identifier = title_parts[0]
                    for dt in downloaded_titles:
                        normalized_identifier = ep_identifier.replace(":", "\uff1a")
                        if dt.startswith(ep_identifier + " -") or dt.startswith(
                            normalized_identifier + " -"
                        ):
                            is_downloaded = True
                            break

        if is_downloaded:
            ep["status"] = "\u2705 Downloaded"
            downloaded_count += 1
        elif not ep.get("youtube_link"):
            ep["status"] = "\U0001f517 No Link"
            no_link_count += 1
        else:
            ep["status"] = "\u2b1c Pending"
            pending_count += 1

    return downloaded_count, pending_count, no_link_count


def generate_index_markdown(
    episodes: list[dict],
    downloaded_count: int,
    pending_count: int,
    no_link_count: int = 0,
) -> str:
    """Generate markdown index content."""
    lines = [
        "# Naruhodo Podcast - Episode Index",
        "",
        f"Total episodes in RSS feed: {len(episodes)}",
        f"Transcripts downloaded: {downloaded_count}",
        f"Pending (with YouTube link): {pending_count}",
        f"Missing YouTube link: {no_link_count}",
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
        status = ep.get("status", "\u2b1c Pending")

        # Prefer structured references when available
        structured_refs = ep.get("structured_references")
        refs = ep.get("references", [])
        refs_md = format_references(refs, structured_refs=structured_refs)

        row = f"| {num} | {title} | {date} | {duration} | {guest} | {summary} | {refs_md} | {status} |"
        lines.append(row)

    return "\n".join(lines)


def format_references(
    refs: list[str],
    max_refs: int = 5,
    structured_refs: Optional[list[dict]] = None,
) -> str:
    """Format reference URLs as markdown links.

    Uses structured_references labels when available, falling back to
    URL-based heuristics for backward compatibility.
    """
    # Use structured references if available
    if structured_refs:
        ref_links = []
        paper_count = 0
        ref_count = 0
        for sr in structured_refs[:max_refs]:
            label = sr.get("label", "Ref")
            # Number duplicate labels
            if label == "Paper":
                paper_count += 1
                if paper_count > 1:
                    label = f"Paper{paper_count}"
            elif label == "Ref":
                ref_count += 1
                label = f"Ref{ref_count}"
            ref_links.append(f"[{label}]({sr['url']})")
        return " ".join(ref_links)

    # Fallback: derive labels from URLs
    if not refs:
        return ""

    ref_links = []
    paper_count = 0
    ref_count = 0
    for ref in refs[:max_refs]:
        if "lattes.cnpq" in ref:
            label = "Lattes"
        elif "doi.org" in ref or "pubmed" in ref.lower():
            paper_count += 1
            label = f"Paper{paper_count}" if paper_count > 1 else "Paper"
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
            ref_count += 1
            label = f"Ref{ref_count}"

        ref_links.append(f"[{label}]({ref})")

    return " ".join(ref_links)


def save_index(content: str, path: Path) -> None:
    """Save index markdown to file atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.info("Updated %s", path)
