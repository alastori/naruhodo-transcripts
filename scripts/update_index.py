#!/usr/bin/env python3
"""Update episode index with download status based on downloaded files and log."""

import os
import re
import json
from datetime import datetime

def get_downloaded_episode_numbers():
    """Get set of downloaded episode numbers from filenames."""
    transcripts_dir = '/Users/alastori/Desktop/Naruhodo-transcripts/transcripts'
    downloaded_numbers = set()
    downloaded_titles = set()

    for filename in os.listdir(transcripts_dir):
        if filename.endswith('.pt.vtt'):
            # Extract episode number from filename (Naruhodo #XXX or Entrevista #XX)
            # E.g., "001 - Naruhodo #457 - Title.pt.vtt" -> 457
            # E.g., "001 - Naruhodo Entrevista #58: Name.pt.vtt" -> E58
            match = re.search(r'Naruhodo\s+#(\d+)', filename)
            if match:
                downloaded_numbers.add(f'N{match.group(1)}')

            match = re.search(r'Entrevista\s+#(\d+)', filename)
            if match:
                downloaded_numbers.add(f'E{match.group(1)}')

            # Also store normalized title for fallback matching
            title_match = re.match(r'\d+ - (.+)\.pt\.vtt$', filename)
            if title_match:
                title = title_match.group(1)
                title = title.replace('：', ':').replace('？', '?').replace('！', '!')
                downloaded_titles.add(title)

    return downloaded_numbers, downloaded_titles

def parse_log_for_status():
    """Parse download log to identify videos with no subtitles."""
    no_subtitles = set()
    rate_limited = set()

    log_path = '/Users/alastori/Desktop/Naruhodo-transcripts/download_log.txt'

    with open(log_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Find videos where subtitles are not available
    # Pattern: [info] videoId: There are no subtitles for the requested languages: pt
    no_sub_pattern = r'\[info\] \S+: There are no subtitles for the requested languages'
    for match in re.finditer(no_sub_pattern, content):
        # This indicates no subtitles available for that video
        no_subtitles.add(match.group(0))

    return no_subtitles

def main():
    # Load episodes
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episodes.json', 'r', encoding='utf-8') as f:
        episodes = json.load(f)

    # Get downloaded episode info
    downloaded_numbers, downloaded_titles = get_downloaded_episode_numbers()
    total_vtt = len([f for f in os.listdir('/Users/alastori/Desktop/Naruhodo-transcripts/transcripts') if f.endswith('.vtt')])
    print(f"Found {total_vtt} VTT files")
    print(f"Unique episode numbers: {len(downloaded_numbers)}")

    # Update status in episodes
    downloaded_count = 0
    pending_count = 0

    for ep in episodes:
        title = ep['title']
        ep_num = ep.get('episode_number', '')

        # Check by episode number first (most reliable)
        is_downloaded = False

        if 'Entrevista' in title and ep_num:
            if f'E{ep_num}' in downloaded_numbers:
                is_downloaded = True
        elif ep_num:
            if f'N{ep_num}' in downloaded_numbers:
                is_downloaded = True

        # Fallback to title matching if number didn't match
        if not is_downloaded:
            normalized_title = title.replace(':', '：').replace('?', '？').replace('!', '！')
            if title in downloaded_titles or normalized_title in downloaded_titles:
                is_downloaded = True
            else:
                # Partial match on main identifier
                title_parts = title.split(' - ')
                if len(title_parts) > 1:
                    ep_identifier = title_parts[0]
                    for dt in downloaded_titles:
                        if ep_identifier.replace(':', '：') in dt or ep_identifier in dt:
                            is_downloaded = True
                            break

        if is_downloaded:
            ep['status'] = '✅ Downloaded'
            downloaded_count += 1
        else:
            ep['status'] = '⬜ Pending'
            pending_count += 1

    print(f"Downloaded: {downloaded_count}")
    print(f"Pending: {pending_count}")

    # Save updated episodes
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episodes.json', 'w', encoding='utf-8') as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)

    # Regenerate the index
    lines = []
    lines.append("# Naruhodo Podcast - Episode Index")
    lines.append("")
    lines.append(f"Total episodes in RSS feed: {len(episodes)}")
    lines.append(f"Transcripts downloaded: {downloaded_count}")
    lines.append(f"Pending (rate-limited): {pending_count}")
    lines.append("")
    lines.append(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Episodes")
    lines.append("")

    # Table header
    lines.append("| # | Title | Date | Duration | Guest | Summary | References | Status |")
    lines.append("|---|-------|------|----------|-------|---------|------------|--------|")

    # Add episodes
    for ep in episodes:
        num = ep.get('episode_number', '')
        title = ep.get('title', '').replace('|', '\\|')
        date = ep.get('date', '')
        duration = ep.get('duration', '')
        guest = ep.get('guest', '').replace('|', '\\|')
        summary = ep.get('summary', '').replace('|', '\\|')
        status = ep.get('status', '⬜ Pending')

        # Format references as markdown links
        refs = ep.get('references', [])
        if refs:
            # Create short link labels
            ref_links = []
            for i, ref in enumerate(refs[:5]):  # Limit to 5 refs
                # Create a short label based on domain
                if 'lattes.cnpq' in ref:
                    label = 'Lattes'
                elif 'doi.org' in ref or 'pubmed' in ref.lower():
                    label = f'Paper{i+1}' if i > 0 else 'Paper'
                elif 'twitter.com' in ref or 'x.com' in ref:
                    label = 'Twitter'
                elif 'instagram.com' in ref:
                    label = 'Instagram'
                elif 'youtube.com' in ref:
                    label = 'Video'
                elif 'wikipedia' in ref:
                    label = 'Wiki'
                elif 'teses.usp' in ref or 'bdtd' in ref:
                    label = 'Tese'
                elif 'scielo' in ref:
                    label = 'SciELO'
                else:
                    label = f'Ref{i+1}'
                ref_links.append(f"[{label}]({ref})")
            refs_md = ' '.join(ref_links)
        else:
            refs_md = ""

        row = f"| {num} | {title} | {date} | {duration} | {guest} | {summary} | {refs_md} | {status} |"
        lines.append(row)

    # Write to file
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episode-index.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    print(f"\nUpdated episode-index.md")

if __name__ == '__main__':
    main()
