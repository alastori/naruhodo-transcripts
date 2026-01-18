"""Parse Naruhodo podcast RSS feed and extract episode metadata."""

import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("naruhodo")

# Naruhodo RSS feed URL
RSS_FEED_URL = "https://feeds.simplecast.com/hwQVm5gy"

# Patterns for sponsor filtering
SPONSOR_PATTERNS = [
    r"orelo\.cc",
    r"bit\.ly/naruhodo",
    r"insider\.com",
    r"insider\.store",
    r"apoie",
    r"apoia\.se",
    r"catarse\.me",
    r"patreon\.com",
    r"picpay",
    r"pix",
    r"doação",
    r"cupom",
    r"desconto",
    r"patrocin",
]

SPONSOR_DOMAINS = [
    "insider.com",
    "insiderstore.com",
    "orelo.cc",
    "apoia.se",
    "catarse.me",
    "patreon.com",
    "picpay.com",
    "creators.insider",
]


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_duration(duration_str: str) -> str:
    """Parse duration from various formats to HH:MM:SS."""
    if not duration_str:
        return ""
    if ":" in duration_str:
        return duration_str
    try:
        total_seconds = int(duration_str)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"
    except ValueError:
        return duration_str


def extract_episode_number(title: str) -> str:
    """Extract episode number from title."""
    match = re.search(r"#(\d+)", title)
    return match.group(1) if match else ""


def extract_guest(title: str, description: str) -> str:
    """Extract guest name from interview episodes."""
    if "Entrevista" in title:
        match = re.search(r"Entrevista\s*#\d+[:\s]+(.+?)$", title)
        if match:
            return match.group(1).strip()
    return ""


def format_date(date_str: str) -> str:
    """Parse and format date to YYYY-MM-DD."""
    if not date_str:
        return ""
    try:
        dt = datetime.strptime(date_str.strip(), "%a, %d %b %Y %H:%M:%S %z")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        try:
            dt = datetime.strptime(date_str.strip()[:25], "%a, %d %b %Y %H:%M:%S")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return date_str


def is_sponsor_context(text: str, url_start: int) -> bool:
    """Check if URL appears in a sponsor context."""
    context_start = max(0, url_start - 200)
    context = text[context_start:url_start].lower()
    for pattern in SPONSOR_PATTERNS:
        if re.search(pattern, context, re.IGNORECASE):
            return True
    return False


def is_sponsor_domain(url: str) -> bool:
    """Check if URL is from a known sponsor domain."""
    url_lower = url.lower()
    for domain in SPONSOR_DOMAINS:
        if domain in url_lower:
            return True
    return False


def extract_references(description: str) -> list[str]:
    """Extract valuable reference URLs from description."""
    if not description:
        return []

    url_pattern = r"https?://[^\s<>\"')\]]+[^\s<>\"')\].,;:!?]"
    references = []

    for match in re.finditer(url_pattern, description):
        url = match.group(0)
        url_start = match.start()

        url = re.sub(r"[.,;:!?\"')\]]+$", "", url)

        if is_sponsor_domain(url):
            continue
        if is_sponsor_context(description, url_start):
            continue
        if "naruhodo.b9.com.br" in url and len(url) < 30:
            continue

        if url not in references:
            references.append(url)

    return references


def synthesize_summary(description: str, title: str, max_chars: int = 120) -> str:
    """Create a synthesized summary from description."""
    if not description:
        return ""

    desc = description
    desc = re.split(r"\*\s*(?:APOIO|PATROCÍN|PARCEIRO|OFERECIMENTO)[:\s]", desc, flags=re.IGNORECASE)[0]
    desc = re.split(r"\*?\s*Naruhodo!?\s*é\s*o\s*podcast", desc, flags=re.IGNORECASE)[0]
    desc = re.sub(r">>\s*OUÇA\s*\([^)]+\)", "", desc)
    desc = re.sub(r"\(\d+min\s*\d*s?\)", "", desc)
    desc = re.sub(r"https?://\S+", "", desc)
    desc = re.sub(r"#\w+", "", desc)
    desc = re.sub(r"\s+", " ", desc).strip()

    if "Entrevista" in title:
        match = re.search(r"chegou a vez d[aoe]\s+(.+?)(?:Só vem|$)", desc, re.IGNORECASE)
        if match:
            credentials = match.group(1).strip()
            if len(credentials) > max_chars:
                for bp in [". ", ", ", " e ", " - "]:
                    idx = credentials[:max_chars].rfind(bp)
                    if idx > 40:
                        credentials = credentials[: idx + 1].strip()
                        break
                else:
                    credentials = credentials[:max_chars].rsplit(" ", 1)[0]
            return f"Entrevista: {credentials}"

    sentences = re.split(r"(?<=[.!?])\s+", desc)
    summary = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15:
            continue
        if re.search(r"(Ken Fujioka|Altay de Souza|Reginaldo Cursino|leigo curioso|cientista PhD)", sentence, re.IGNORECASE):
            continue
        if re.search(r"^(confira|só vem|vem com)", sentence, re.IGNORECASE):
            continue

        if len(summary) + len(sentence) + 2 <= max_chars:
            summary = f"{summary} {sentence}" if summary else sentence
        else:
            if summary:
                break
            if len(sentence) > max_chars:
                truncated = sentence[:max_chars]
                for bp in ["; ", ", ", " - ", " e ", " ou "]:
                    idx = truncated.rfind(bp)
                    if idx > 40:
                        summary = truncated[: idx + 1].strip()
                        break
                else:
                    summary = truncated.rsplit(" ", 1)[0] + "..."
            else:
                summary = sentence
            break

    summary = summary.strip()
    if summary and summary[-1] not in ".!?":
        if not summary.endswith("..."):
            summary = summary.rstrip(",;:")

    return summary


def fetch_rss_feed(url: str = RSS_FEED_URL, cache_path: Optional[Path] = None) -> str:
    """Fetch RSS feed from URL or cache.

    Args:
        url: RSS feed URL
        cache_path: Optional path to cache the feed

    Returns:
        RSS feed XML content
    """
    logger.info("Fetching RSS feed from %s", url)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    content = response.text

    if cache_path:
        cache_path.write_text(content, encoding="utf-8")
        logger.debug("Cached RSS feed to %s", cache_path)

    return content


def parse_rss(content: str) -> list[dict]:
    """Parse RSS feed and extract episodes.

    Args:
        content: RSS XML content or path to RSS file

    Returns:
        List of episode dictionaries
    """
    # Check if content is a file path
    if len(content) < 500 and Path(content).exists():
        content = Path(content).read_text(encoding="utf-8")

    root = ET.fromstring(content)

    namespaces = {
        "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
        "content": "http://purl.org/rss/1.0/modules/content/",
        "atom": "http://www.w3.org/2005/Atom",
    }

    episodes = []

    for item in root.findall(".//item"):
        title = item.find("title")
        title_text = title.text if title is not None else ""

        pub_date = item.find("pubDate")
        pub_date_text = pub_date.text if pub_date is not None else ""

        duration = item.find("itunes:duration", namespaces)
        if duration is None:
            duration = item.find("duration")
        duration_text = duration.text if duration is not None else ""

        description = item.find("content:encoded", namespaces)
        if description is None:
            description = item.find("description")
        description_text = description.text if description is not None else ""

        link = item.find("link")
        link_text = link.text if link is not None else ""

        guid = item.find("guid")
        if not link_text and guid is not None:
            link_text = guid.text or ""

        clean_desc = clean_html(description_text)

        episode = {
            "title": title_text,
            "episode_number": extract_episode_number(title_text),
            "date": format_date(pub_date_text),
            "duration": parse_duration(duration_text),
            "description": clean_desc,
            "summary": synthesize_summary(clean_desc, title_text),
            "guest": extract_guest(title_text, clean_desc),
            "link": link_text,
            "youtube_link": "",
            "status": "⬜ Pending",
            "references": extract_references(description_text),
        }

        episodes.append(episode)

    return episodes


def load_episodes(path: Path) -> list[dict]:
    """Load episodes from JSON file."""
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save_episodes(episodes: list[dict], path: Path):
    """Save episodes to JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(episodes, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def merge_episodes(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new episodes with existing, preserving download status.

    Args:
        existing: Existing episodes with status
        new: New episodes from RSS

    Returns:
        Merged episode list
    """
    # Create lookup by title
    existing_by_title = {ep["title"]: ep for ep in existing}

    merged = []
    for ep in new:
        if ep["title"] in existing_by_title:
            # Preserve status and youtube_link from existing
            old = existing_by_title[ep["title"]]
            ep["status"] = old.get("status", ep["status"])
            ep["youtube_link"] = old.get("youtube_link", ep.get("youtube_link", ""))
        merged.append(ep)

    return merged
