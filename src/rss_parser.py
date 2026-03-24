"""Parse Naruhodo podcast RSS feed and extract episode metadata."""

import json
import logging
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from .config import (
    RSS_FEED_URL,
    RSS_INITIAL_RETRY_DELAY,
    RSS_MAX_RETRIES,
    RSS_REQUEST_TIMEOUT,
    RSS_RETRY_BACKOFF_FACTOR,
)

logger = logging.getLogger("naruhodo")

# --- Pre-compiled regex patterns ---

_RE_HTML_TAGS = re.compile(r"<[^>]+>")
_RE_WHITESPACE = re.compile(r"\s+")
_RE_EPISODE_NUMBER = re.compile(r"#(\d+)")
_RE_INTERVIEW_GUEST = re.compile(r"Entrevista\s*#\d+[:\s]+(.+?)$")
# URL pattern: allows parentheses in URLs (for Wikipedia, Lancet DOIs, etc.)
_RE_URL = re.compile(r"https?://[^\s<>\"'\]]+")
_RE_URL_TRAILING_PUNCT = re.compile(r"[.,;:!?\"'\]]+$")
_RE_DOI = re.compile(r"10\.\d{4,}/[^\s]+")
_RE_PMID = re.compile(r"/pubmed/(\d+)")

# Episode type and topic extraction
_RE_INTERVIEW_TITLE = re.compile(r"Entrevista\s*#(\d+)")
_RE_REGULAR_TITLE = re.compile(r"Naruhodo\s*#(\d+)")
_RE_TOPIC_REGULAR = re.compile(r"Naruhodo\s*#\d+\s*[-\u2013\u2014]\s*(.+)")
_RE_TOPIC_INTERVIEW = re.compile(r"Entrevista\s*#\d+\s*[-\u2013\u2014:\s]+(.+)")
_RE_TOPIC_EXTRA = re.compile(r"Extra\s*(?:#\d+)?\s*[-\u2013\u2014:\s]+(.+)", re.IGNORECASE)
_RE_TOPIC_FALLBACK = re.compile(r"\s*[-\u2013\u2014]\s*")

# Series detection
_RE_SERIES_PART = re.compile(
    r"\(?\s*(?:Parte|Pt\.?|Part)\s+(\d+)\s*(?:de|of|/)\s*(\d+)\s*\)?",
    re.IGNORECASE,
)

# Sponsor filtering (single combined pattern)
_RE_SPONSOR = re.compile(
    r"orelo\.cc|bit\.ly/naruhodo|insider\.com|insider\.store|apoie|apoia\.se|"
    r"catarse\.me|patreon\.com|picpay|pix|doa\u00e7\u00e3o|cupom|desconto|patrocin",
    re.IGNORECASE,
)

SPONSOR_DOMAINS = frozenset([
    "insider.com", "insiderstore.com", "orelo.cc", "apoia.se",
    "catarse.me", "patreon.com", "picpay.com", "creators.insider",
    "bit.ly",
])

# Junk domains: false positives and tracking artifacts
JUNK_DOMAINS = frozenset([
    "b.sc", "m.sc",  # False positives from B.Sc/M.Sc abbreviations in text
    "feedburner.com", "feeds.feedburner.com",  # RSS redirect artifacts
    "gate.sc",  # SoundCloud gate URLs
])

# Reference domain classification sets
ACADEMIC_DOMAINS = frozenset([
    "doi.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
    "scielo.br", "scielo.org", "scholar.google.com",
    "sciencedirect.com", "springer.com", "link.springer.com",
    "nature.com", "wiley.com", "onlinelibrary.wiley.com",
    "tandfonline.com", "sagepub.com", "journals.sagepub.com",
    "pnas.org", "science.org", "aps.org", "cell.com",
    "frontiersin.org", "mdpi.com", "plos.org", "plosone.org",
    "bmj.com", "thelancet.com", "nejm.org",
    "psycnet.apa.org", "academic.oup.com",
    "arxiv.org", "biorxiv.org", "medrxiv.org", "ssrn.com",
    "researchgate.net", "jstor.org", "cambridge.org",
    "annualreviews.org", "jamanetwork.com", "royalsocietypublishing.org",
    "dl.acm.org", "jneurosci.org", "apa.org",
])

CREDENTIAL_DOMAINS = frozenset(["lattes.cnpq.br", "orcid.org"])

THESIS_DOMAINS = frozenset(["teses.usp.br", "bdtd.ibict.br", "repositorio.unicamp.br"])

SOCIAL_DOMAINS = frozenset([
    "twitter.com", "x.com", "instagram.com", "facebook.com",
    "linkedin.com", "threads.net",
])

ENCYCLOPEDIA_DOMAINS = frozenset(["wikipedia.org"])

# Summary synthesis patterns
_RE_SPONSOR_SPLIT = re.compile(
    r"\*\s*(?:APOIO|PATROC\u00cdN|PARCEIRO|OFERECIMENTO)[:\s]", re.IGNORECASE
)
_RE_PODCAST_SPLIT = re.compile(r"\*?\s*Naruhodo!?\s*\u00e9\s*o\s*podcast", re.IGNORECASE)
_RE_LISTEN_CTA = re.compile(r">>\s*OU\u00c7A\s*\([^)]+\)")
_RE_DURATION_TAG = re.compile(r"\(\d+min\s*\d*s?\)")
_RE_URL_IN_TEXT = re.compile(r"https?://\S+")
_RE_HASHTAG = re.compile(r"#\w+")
_RE_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_RE_HOST_NAMES = re.compile(
    r"(Ken Fujioka|Altay de Souza|Reginaldo Cursino|leigo curioso|cientista PhD)",
    re.IGNORECASE,
)
_RE_CTA_START = re.compile(r"^(confira|s\u00f3 vem|vem com)", re.IGNORECASE)
_RE_INTERVIEW_CREDENTIALS = re.compile(
    r"chegou a vez d[aoe]\s+(.+?)(?:S\u00f3 vem|$)", re.IGNORECASE
)


# --- Utility functions ---


def clean_html(text: str) -> str:
    """Remove HTML tags and clean up text."""
    if not text:
        return ""
    text = _RE_HTML_TAGS.sub(" ", text)
    text = unescape(text)
    text = _RE_WHITESPACE.sub(" ", text).strip()
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
    match = _RE_EPISODE_NUMBER.search(title)
    return match.group(1) if match else ""


def extract_episode_type(title: str) -> str:
    """Determine episode type from title.

    Returns: "regular", "interview", "extra", or "other"
    """
    if "Entrevista" in title:
        return "interview"
    if "Extra" in title:
        return "extra"
    if _RE_REGULAR_TITLE.search(title):
        return "regular"
    return "other"


def extract_topic(title: str) -> str:
    """Extract the topic/subject from the episode title.

    Examples:
        "Naruhodo #400 - Por que gostamos de musica?" -> "Por que gostamos de musica?"
        "Entrevista #50: Dr. Maria Santos" -> "Dr. Maria Santos"
    """
    for pattern in (_RE_TOPIC_REGULAR, _RE_TOPIC_INTERVIEW, _RE_TOPIC_EXTRA):
        match = pattern.search(title)
        if match:
            return match.group(1).strip()
    # Fallback: split on common separators
    parts = _RE_TOPIC_FALLBACK.split(title, maxsplit=1)
    if len(parts) > 1:
        return parts[1].strip()
    return ""


def detect_series(title: str) -> Optional[dict]:
    """Detect if episode is part of a multi-part series.

    Returns:
        Dict with "part" and "total" keys, or None
    """
    match = _RE_SERIES_PART.search(title)
    if match:
        return {"part": int(match.group(1)), "total": int(match.group(2))}
    return None


def extract_guest(title: str, description: str) -> str:
    """Extract guest name from interview episodes."""
    if "Entrevista" in title:
        match = _RE_INTERVIEW_GUEST.search(title)
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
    context = text[context_start:url_start]
    return bool(_RE_SPONSOR.search(context))


def is_sponsor_domain(url: str) -> bool:
    """Check if URL is from a known sponsor domain."""
    domain = _get_base_domain(url)
    return _matches_domain_set(domain, SPONSOR_DOMAINS)


def _get_base_domain(url: str) -> str:
    """Extract base domain from URL, stripping www prefix."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def _matches_domain_set(domain: str, domain_set: frozenset) -> bool:
    """Check if domain or parent domain is in the set."""
    if domain in domain_set:
        return True
    for d in domain_set:
        if domain.endswith("." + d):
            return True
    return False


def _is_junk_url(url: str) -> bool:
    """Check if URL is from a known junk/false-positive domain."""
    domain = _get_base_domain(url)
    return _matches_domain_set(domain, JUNK_DOMAINS)


def _is_naruhodo_self_reference(url: str) -> bool:
    """Check if URL is a cross-reference to another Naruhodo episode."""
    return "naruhodo.b9.com.br" in url


def _clean_extracted_url(url: str) -> str:
    """Clean extracted URL: strip trailing punctuation and balance parentheses."""
    url = _RE_URL_TRAILING_PUNCT.sub("", url)
    # Balance parentheses: strip trailing ) without matching (
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    # Strip any remaining trailing punctuation after paren balancing
    url = _RE_URL_TRAILING_PUNCT.sub("", url)
    return url


def _generate_reference_label(domain: str, ref_type: str) -> str:
    """Generate a human-readable label for a reference."""
    if ref_type == "academic":
        return "Paper"
    if ref_type == "credential":
        if "lattes" in domain:
            return "Lattes"
        if "orcid" in domain:
            return "ORCID"
        return "Profile"
    if ref_type == "thesis":
        return "Tese"
    if ref_type == "video":
        return "Video"
    if ref_type == "cross_reference":
        return "Naruhodo"
    if ref_type == "social":
        if "twitter" in domain or "x.com" in domain:
            return "Twitter"
        if "instagram" in domain:
            return "Instagram"
        if "linkedin" in domain:
            return "LinkedIn"
        return "Social"
    if ref_type == "encyclopedia":
        return "Wiki"
    return "Ref"


def classify_reference(url: str) -> dict:
    """Classify a reference URL into a structured object.

    Returns:
        Dict with keys: url, domain, type, label, and optionally doi/pmid
    """
    domain = _get_base_domain(url)

    # Cross-references to other Naruhodo episodes
    if _is_naruhodo_self_reference(url):
        ref_type = "cross_reference"
    elif _matches_domain_set(domain, ACADEMIC_DOMAINS):
        ref_type = "academic"
    elif _matches_domain_set(domain, CREDENTIAL_DOMAINS):
        ref_type = "credential"
    elif _matches_domain_set(domain, THESIS_DOMAINS):
        ref_type = "thesis"
    elif _matches_domain_set(domain, SOCIAL_DOMAINS):
        ref_type = "social"
    elif _matches_domain_set(domain, ENCYCLOPEDIA_DOMAINS):
        ref_type = "encyclopedia"
    elif "youtube.com" in domain or "youtu.be" in domain:
        ref_type = "video"
    else:
        ref_type = "other"

    # Extract identifiers
    doi_match = _RE_DOI.search(url)
    doi = doi_match.group(0) if doi_match else None
    if doi:
        ref_type = "academic"

    pmid_match = _RE_PMID.search(url)
    pmid = pmid_match.group(1) if pmid_match else None
    if pmid:
        ref_type = "academic"

    # Generate label
    label = _generate_reference_label(domain, ref_type)

    result = {"url": url, "domain": domain, "type": ref_type, "label": label}
    if doi:
        result["doi"] = doi
    if pmid:
        result["pmid"] = pmid

    return result


def _extract_all_urls(description: str) -> list[str]:
    """Extract all valid URLs from description, filtering junk and sponsors."""
    if not description:
        return []

    urls = []
    for match in _RE_URL.finditer(description):
        url = _clean_extracted_url(match.group(0))
        url_start = match.start()

        if not url or len(url) < 10:
            continue
        if _is_junk_url(url):
            continue
        if is_sponsor_domain(url):
            continue
        if is_sponsor_context(description, url_start):
            continue

        if url not in urls:
            urls.append(url)

    return urls


def extract_references(description: str) -> list[str]:
    """Extract valuable reference URLs from description.

    Returns a flat list of external reference URL strings.
    Filters out sponsor links, junk domains, and self-references.
    """
    urls = _extract_all_urls(description)
    return [url for url in urls if not _is_naruhodo_self_reference(url)]


def extract_structured_references(description: str) -> list[dict]:
    """Extract and classify all reference URLs from description.

    Returns a list of structured reference objects including cross-references.
    """
    urls = _extract_all_urls(description)
    return [classify_reference(url) for url in urls]


def synthesize_summary(description: str, title: str, max_chars: int = 120) -> str:
    """Create a synthesized summary from description."""
    if not description:
        return ""

    desc = description
    desc = _RE_SPONSOR_SPLIT.split(desc)[0]
    desc = _RE_PODCAST_SPLIT.split(desc)[0]
    desc = _RE_LISTEN_CTA.sub("", desc)
    desc = _RE_DURATION_TAG.sub("", desc)
    desc = _RE_URL_IN_TEXT.sub("", desc)
    desc = _RE_HASHTAG.sub("", desc)
    desc = _RE_WHITESPACE.sub(" ", desc).strip()

    if "Entrevista" in title:
        match = _RE_INTERVIEW_CREDENTIALS.search(desc)
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

    sentences = _RE_SENTENCES.split(desc)
    summary = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 15:
            continue
        if _RE_HOST_NAMES.search(sentence):
            continue
        if _RE_CTA_START.search(sentence):
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


def backfill_episode_fields(ep: dict) -> None:
    """Ensure episode has all current schema fields, deriving from existing data.

    Called during load and merge to migrate old episodes to the current schema.
    Fields that require RSS data (guid, audio_url, image_url, raw_description)
    are set to empty defaults if missing.
    """
    title = ep.get("title", "")
    if "episode_type" not in ep:
        ep["episode_type"] = extract_episode_type(title)
    if "topic" not in ep:
        ep["topic"] = extract_topic(title)
    if "series" not in ep:
        ep["series"] = detect_series(title)
    if "guid" not in ep:
        ep["guid"] = ""
    if "audio_url" not in ep:
        ep["audio_url"] = ""
    if "image_url" not in ep:
        ep["image_url"] = ""
    if "raw_description" not in ep:
        ep["raw_description"] = ""
    if "structured_references" not in ep:
        refs = ep.get("references", [])
        ep["structured_references"] = [classify_reference(url) for url in refs]


def fetch_rss_feed(url: str = RSS_FEED_URL, cache_path: Optional[Path] = None) -> str:
    """Fetch RSS feed from URL with retry logic.

    Retries on connection errors, timeouts, and server errors (5xx).
    Client errors (4xx) are raised immediately.
    """
    logger.info("Fetching RSS feed from %s", url)

    if RSS_MAX_RETRIES < 1:
        raise ValueError("RSS_MAX_RETRIES must be at least 1")

    delay = RSS_INITIAL_RETRY_DELAY
    last_error = None

    for attempt in range(RSS_MAX_RETRIES):
        try:
            response = requests.get(url, timeout=RSS_REQUEST_TIMEOUT)
            response.raise_for_status()
            content = response.text

            if cache_path:
                cache_path.write_text(content, encoding="utf-8")
                logger.debug("Cached RSS feed to %s", cache_path)

            return content

        except requests.HTTPError as e:
            # Only retry on server errors (5xx), not client errors (4xx)
            if e.response is not None and e.response.status_code < 500:
                raise
            last_error = e
            if attempt < RSS_MAX_RETRIES - 1:
                logger.warning(
                    "RSS fetch failed (attempt %d/%d): HTTP %s. Retrying in %.1fs...",
                    attempt + 1,
                    RSS_MAX_RETRIES,
                    e.response.status_code if e.response is not None else "unknown",
                    delay,
                )
                time.sleep(delay)
                delay *= RSS_RETRY_BACKOFF_FACTOR
            else:
                logger.error(
                    "RSS fetch failed after %d attempts: %s", RSS_MAX_RETRIES, e
                )

        except (requests.Timeout, requests.ConnectionError) as e:
            last_error = e
            if attempt < RSS_MAX_RETRIES - 1:
                logger.warning(
                    "RSS fetch failed (attempt %d/%d): %s. Retrying in %.1fs...",
                    attempt + 1,
                    RSS_MAX_RETRIES,
                    str(e),
                    delay,
                )
                time.sleep(delay)
                delay *= RSS_RETRY_BACKOFF_FACTOR
            else:
                logger.error(
                    "RSS fetch failed after %d attempts: %s",
                    RSS_MAX_RETRIES,
                    str(e),
                )

    raise last_error


def parse_rss(content: str) -> list[dict]:
    """Parse RSS feed and extract episodes with full metadata.

    Args:
        content: RSS XML content

    Returns:
        List of episode dictionaries with comprehensive metadata
    """
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
        guid_text = guid.text if guid is not None else ""
        if not link_text and guid_text:
            link_text = guid_text

        # Audio URL from enclosure
        enclosure = item.find("enclosure")
        audio_url = ""
        if enclosure is not None:
            audio_url = enclosure.get("url", "")

        # Per-episode image
        itunes_image = item.find("itunes:image", namespaces)
        image_url = ""
        if itunes_image is not None:
            image_url = itunes_image.get("href", "")

        clean_desc = clean_html(description_text)

        episode = {
            "title": title_text,
            "episode_number": extract_episode_number(title_text),
            "episode_type": extract_episode_type(title_text),
            "topic": extract_topic(title_text),
            "date": format_date(pub_date_text),
            "duration": parse_duration(duration_text),
            "description": clean_desc,
            "raw_description": description_text,
            "summary": synthesize_summary(clean_desc, title_text),
            "guest": extract_guest(title_text, clean_desc),
            "link": link_text,
            "youtube_link": "",
            "guid": guid_text,
            "audio_url": audio_url,
            "image_url": image_url,
            "series": detect_series(title_text),
            "status": "\u2b1c Pending",
            "references": extract_references(description_text),
            "structured_references": extract_structured_references(description_text),
        }

        episodes.append(episode)

    return episodes


def _atomic_write(path: Path, content: str) -> None:
    """Write content to file atomically using temp file + rename.

    Prevents data corruption if the process crashes mid-write.
    """
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


def load_episodes(path: Path) -> list[dict]:
    """Load episodes from JSON file, with corrupt-file recovery and schema backfill."""
    if not path.exists():
        return []
    try:
        episodes = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Corrupt episodes file %s: %s. Starting fresh.", path, e)
        return []
    for ep in episodes:
        backfill_episode_fields(ep)
    return episodes


def save_episodes(episodes: list[dict], path: Path) -> None:
    """Save episodes to JSON file atomically."""
    content = json.dumps(episodes, ensure_ascii=False, indent=2)
    _atomic_write(path, content)


def merge_episodes(existing: list[dict], new: list[dict]) -> list[dict]:
    """Merge new episodes with existing, preserving download status and YouTube links.

    Uses guid as primary merge key, with title as fallback for old data.
    Episodes in existing but not in new are preserved to avoid data loss.

    Args:
        existing: Existing episodes with status
        new: New episodes from RSS

    Returns:
        Merged episode list
    """
    # Build lookups from existing data
    existing_by_guid: dict[str, dict] = {}
    existing_by_title: dict[str, dict] = {}
    for ep in existing:
        if ep.get("guid"):
            existing_by_guid[ep["guid"]] = ep
        existing_by_title[ep["title"]] = ep

    seen_guids: set[str] = set()
    seen_titles: set[str] = set()

    merged = []
    for ep in new:
        guid = ep.get("guid", "")
        title = ep["title"]

        # Look up existing by guid first, then title
        old = None
        if guid and guid in existing_by_guid:
            old = existing_by_guid[guid]
        elif title in existing_by_title:
            old = existing_by_title[title]

        if old:
            # Preserve user-managed fields from existing
            ep["status"] = old.get("status", ep["status"])
            ep["youtube_link"] = old.get("youtube_link", ep.get("youtube_link", ""))

        backfill_episode_fields(ep)
        merged.append(ep)
        if guid:
            seen_guids.add(guid)
        seen_titles.add(title)

    # Preserve episodes from existing that aren't in the new feed
    for ep in existing:
        guid = ep.get("guid", "")
        if guid and guid in seen_guids:
            continue
        if ep["title"] in seen_titles:
            continue
        backfill_episode_fields(ep)
        merged.append(ep)

    return merged
