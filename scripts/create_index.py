#!/usr/bin/env python3
"""Create episode-index.md from parsed episode data."""

import json
import re

def escape_markdown(text):
    """Escape special markdown characters in table cells."""
    if not text:
        return ""
    # Replace pipe characters that would break table
    text = text.replace('|', '\\|')
    # Replace newlines
    text = text.replace('\n', ' ')
    return text

def main():
    # Load episodes
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episodes.json', 'r', encoding='utf-8') as f:
        episodes = json.load(f)

    # Sort by date (newest first, which is the RSS order)
    # Episodes are already in reverse chronological order from RSS

    # Create markdown content
    lines = []
    lines.append("# Naruhodo Podcast - Episode Index")
    lines.append("")
    lines.append(f"Total episodes: {len(episodes)}")
    lines.append("")
    lines.append("Last updated: Auto-generated from RSS feed")
    lines.append("")
    lines.append("## Episodes")
    lines.append("")

    # Table header
    lines.append("| # | Title | Date | Duration | Guest | Summary | RSS Link | YouTube | Status |")
    lines.append("|---|-------|------|----------|-------|---------|----------|---------|--------|")

    # Add episodes
    for ep in episodes:
        num = ep.get('episode_number', '')
        title = escape_markdown(ep.get('title', ''))
        date = ep.get('date', '')
        duration = ep.get('duration', '')
        guest = escape_markdown(ep.get('guest', ''))
        summary = escape_markdown(ep.get('summary', ''))[:100]  # Limit summary length
        link = ep.get('link', '')
        youtube = ep.get('youtube_link', '')
        status = ep.get('status', '⬜ Pending')

        # Create link markdown if available
        if link:
            link_md = f"[Link]({link})"
        else:
            link_md = ""

        if youtube:
            youtube_md = f"[YT]({youtube})"
        else:
            youtube_md = ""

        row = f"| {num} | {title} | {date} | {duration} | {guest} | {summary} | {link_md} | {youtube_md} | {status} |"
        lines.append(row)

    # Write to file
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episode-index.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"Created episode-index.md with {len(episodes)} episodes")

if __name__ == '__main__':
    main()
