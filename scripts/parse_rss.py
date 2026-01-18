#!/usr/bin/env python3
"""Parse Naruhodo podcast RSS feed and create episode index."""

import xml.etree.ElementTree as ET
import re
from datetime import datetime
from html import unescape
import json

def clean_html(text):
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities
    text = unescape(text)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def parse_duration(duration_str):
    """Parse duration from various formats to HH:MM:SS."""
    if not duration_str:
        return ""

    # If already in HH:MM:SS or MM:SS format
    if ':' in duration_str:
        return duration_str

    # If in seconds
    try:
        total_seconds = int(duration_str)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"
    except ValueError:
        return duration_str

def extract_episode_number(title):
    """Extract episode number from title."""
    # Match patterns like "Naruhodo #457", "Naruhodo Entrevista #57", etc.
    match = re.search(r'#(\d+)', title)
    if match:
        return match.group(1)
    return ""

def extract_guest(title, description):
    """Extract guest name from interview episodes."""
    # Check if it's an interview episode
    if 'Entrevista' in title:
        # Try to extract name after the colon in title
        match = re.search(r'Entrevista\s*#\d+[:\s]+(.+?)$', title)
        if match:
            return match.group(1).strip()
    return ""

def format_date(date_str):
    """Parse and format date to YYYY-MM-DD."""
    if not date_str:
        return ""
    try:
        # RSS date format: "Mon, 12 Jan 2026 03:00:00 +0000"
        dt = datetime.strptime(date_str.strip(), "%a, %d %b %Y %H:%M:%S %z")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            # Try without timezone
            dt = datetime.strptime(date_str.strip()[:25], "%a, %d %b %Y %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return date_str

def create_summary(description, max_chars=100):
    """Create a concise summary from description."""
    if not description:
        return ""

    # Clean the description
    desc = clean_html(description)

    # Remove common podcast boilerplate
    desc = re.sub(r'(Apresenta(ção|do por)|Hosted by|Patrocin|Apoio|#\w+|https?://\S+|@\w+).*', '', desc, flags=re.IGNORECASE)

    # Get first sentence or two
    sentences = re.split(r'[.!?]+', desc)
    summary = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 10:
            continue
        if len(summary) + len(sentence) + 2 <= max_chars:
            if summary:
                summary += ". " + sentence
            else:
                summary = sentence
        else:
            break

    if not summary and desc:
        # Just take first part if no good sentences
        summary = desc[:max_chars]
        if len(desc) > max_chars:
            # Cut at last word boundary
            summary = summary.rsplit(' ', 1)[0]

    return summary.strip()

def parse_rss(filename):
    """Parse RSS feed and extract episodes."""
    tree = ET.parse(filename)
    root = tree.getroot()

    # Define namespaces
    namespaces = {
        'itunes': 'http://www.itunes.com/dtds/podcast-1.0.dtd',
        'content': 'http://purl.org/rss/1.0/modules/content/',
        'atom': 'http://www.w3.org/2005/Atom'
    }

    episodes = []

    # Find all items
    for item in root.findall('.//item'):
        title = item.find('title')
        title_text = title.text if title is not None else ""

        pub_date = item.find('pubDate')
        pub_date_text = pub_date.text if pub_date is not None else ""

        # Try itunes:duration first, then duration
        duration = item.find('itunes:duration', namespaces)
        if duration is None:
            duration = item.find('duration')
        duration_text = duration.text if duration is not None else ""

        # Get description - try content:encoded first for full content
        description = item.find('content:encoded', namespaces)
        if description is None:
            description = item.find('description')
        description_text = description.text if description is not None else ""

        link = item.find('link')
        link_text = link.text if link is not None else ""

        # Get guid as fallback for link
        guid = item.find('guid')
        if not link_text and guid is not None:
            link_text = guid.text

        episode = {
            'title': title_text,
            'episode_number': extract_episode_number(title_text),
            'date': format_date(pub_date_text),
            'duration': parse_duration(duration_text),
            'description': clean_html(description_text),
            'summary': create_summary(description_text),
            'guest': extract_guest(title_text, description_text),
            'link': link_text,
            'youtube_link': '',
            'status': '⬜ Pending'
        }

        episodes.append(episode)

    return episodes

def main():
    episodes = parse_rss('/Users/alastori/Desktop/Naruhodo-transcripts/rss_feed.xml')

    print(f"Found {len(episodes)} episodes")

    # Save as JSON for further processing
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episodes.json', 'w', encoding='utf-8') as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)

    print("Saved episodes.json")

    # Print first few for verification
    for i, ep in enumerate(episodes[:5]):
        print(f"\n--- Episode {i+1} ---")
        print(f"Title: {ep['title']}")
        print(f"Number: {ep['episode_number']}")
        print(f"Date: {ep['date']}")
        print(f"Duration: {ep['duration']}")
        print(f"Guest: {ep['guest']}")
        print(f"Summary: {ep['summary']}")

if __name__ == '__main__':
    main()
