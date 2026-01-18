#!/usr/bin/env python3
"""
Enhance episode data with:
1. Synthesized summaries (not truncated)
2. Reference links (excluding sponsors)
"""

import json
import re
from typing import List, Tuple

# Sponsor/support patterns to exclude
SPONSOR_PATTERNS = [
    r'orelo\.cc', r'bit\.ly/naruhodo', r'insider\.com', r'insider\.store',
    r'apoie', r'apoia\.se', r'catarse\.me', r'patreon\.com',
    r'picpay', r'pix', r'doação', r'contribu',
    r'cupom', r'desconto', r'promoção', r'black\s*(friday|november)',
    r'patrocin', r'parceiro', r'apresent',
]

# Domain patterns that are likely sponsors
SPONSOR_DOMAINS = [
    'insider.com', 'insiderstore.com', 'orelo.cc', 'apoia.se', 'catarse.me', 'patreon.com',
    'picpay.com', 'nubank.com', 'sympla.com', 'hotmart.com', 'creators.insider',
]

# Valuable reference patterns
VALUABLE_PATTERNS = [
    r'lattes\.cnpq\.br',
    r'doi\.org',
    r'pubmed',
    r'scholar\.google',
    r'researchgate',
    r'academia\.edu',
    r'arxiv\.org',
    r'scielo',
    r'wikipedia\.org',
    r'youtube\.com/watch',  # Video references
    r'twitter\.com|x\.com',  # Guest social media
    r'instagram\.com',
    r'linkedin\.com',
    r'orcid\.org',
]

def is_sponsor_context(text: str, url_start: int) -> bool:
    """Check if URL appears in a sponsor context."""
    # Get surrounding context (200 chars before URL)
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

def extract_references(description: str) -> List[str]:
    """Extract valuable reference URLs from description."""
    if not description:
        return []

    # Find all URLs
    url_pattern = r'https?://[^\s<>"\')\]]+[^\s<>"\')\].,;:!?]'

    references = []
    for match in re.finditer(url_pattern, description):
        url = match.group(0)
        url_start = match.start()

        # Clean up URL (remove trailing punctuation)
        url = re.sub(r'[.,;:!?\'")\]]+$', '', url)

        # Skip if it's a sponsor domain
        if is_sponsor_domain(url):
            continue

        # Skip if in sponsor context
        if is_sponsor_context(description, url_start):
            continue

        # Skip the main podcast URL
        if 'naruhodo.b9.com.br' in url and len(url) < 30:
            continue

        # Check if it matches valuable patterns (prioritize these)
        is_valuable = any(re.search(p, url, re.IGNORECASE) for p in VALUABLE_PATTERNS)

        # Skip generic social media links that aren't guest profiles
        if re.search(r'(twitter|instagram|x)\.com/?$', url):
            continue

        if is_valuable or not is_sponsor_domain(url):
            # Clean and add
            if url not in references:
                references.append(url)

    return references

def extract_guest_socials(description: str, title: str) -> List[str]:
    """Extract guest social media from description."""
    socials = []

    # Look for patterns like "@username" mentions with context
    # Twitter/X handles
    twitter_pattern = r'(?:twitter|x)(?:\.com)?[:/\s]+@?(\w+)|@(\w+)(?:\s+(?:no\s+)?(?:twitter|x))'
    for match in re.finditer(twitter_pattern, description, re.IGNORECASE):
        handle = match.group(1) or match.group(2)
        if handle and handle.lower() not in ['naruhodo', 'b9', 'insider']:
            socials.append(f"https://twitter.com/{handle}")

    # Instagram handles
    insta_pattern = r'instagram[:/\s]+@?(\w+)|@(\w+)(?:\s+(?:no\s+)?instagram)'
    for match in re.finditer(insta_pattern, description, re.IGNORECASE):
        handle = match.group(1) or match.group(2)
        if handle and handle.lower() not in ['naruhodo', 'b9', 'insider']:
            socials.append(f"https://instagram.com/{handle}")

    return socials

def synthesize_summary(description: str, title: str, max_chars: int = 120) -> str:
    """
    Create a synthesized summary from description.
    Focus on the core topic/question, not boilerplate.
    """
    if not description:
        return ""

    # Remove common boilerplate sections
    desc = description

    # Remove sponsor sections (everything after APOIO:, PATROCÍNIO:, etc.)
    desc = re.split(r'\*\s*(?:APOIO|PATROCÍN|PARCEIRO|OFERECIMENTO)[:\s]', desc, flags=re.IGNORECASE)[0]

    # Remove "Naruhodo! é o podcast..." boilerplate
    desc = re.split(r'\*?\s*Naruhodo!?\s*é\s*o\s*podcast', desc, flags=re.IGNORECASE)[0]

    # Remove ">> OUÇA" and duration info
    desc = re.sub(r'>>\s*OUÇA\s*\([^)]+\)', '', desc)
    desc = re.sub(r'\(\d+min\s*\d*s?\)', '', desc)

    # Remove URLs
    desc = re.sub(r'https?://\S+', '', desc)

    # Remove hashtags
    desc = re.sub(r'#\w+', '', desc)

    # Clean up whitespace
    desc = re.sub(r'\s+', ' ', desc).strip()

    # For interview episodes, create a specific format
    if 'Entrevista' in title:
        # Extract guest credentials from description
        match = re.search(r'chegou a vez d[aoe]\s+(.+?)(?:Só vem|$)', desc, re.IGNORECASE)
        if match:
            credentials = match.group(1).strip()
            # Truncate credentials intelligently
            if len(credentials) > max_chars:
                # Find a good break point
                break_points = ['. ', ', ', ' e ', ' - ']
                for bp in break_points:
                    idx = credentials[:max_chars].rfind(bp)
                    if idx > 40:
                        credentials = credentials[:idx+1].strip()
                        break
                else:
                    credentials = credentials[:max_chars].rsplit(' ', 1)[0]
            return f"Entrevista: {credentials}"

    # For regular episodes, extract the main question/topic
    # Usually the first 1-2 sentences contain the topic

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', desc)

    summary = ""
    for sentence in sentences:
        sentence = sentence.strip()
        # Skip very short sentences or metadata
        if len(sentence) < 15:
            continue
        # Skip if it's about hosts/production
        if re.search(r'(Ken Fujioka|Altay de Souza|Reginaldo Cursino|leigo curioso|cientista PhD)', sentence, re.IGNORECASE):
            continue
        # Skip "confira" type sentences
        if re.search(r'^(confira|só vem|vem com)', sentence, re.IGNORECASE):
            continue

        if len(summary) + len(sentence) + 2 <= max_chars:
            if summary:
                summary += " " + sentence
            else:
                summary = sentence
        else:
            # If we have something, stop
            if summary:
                break
            # Otherwise, truncate this sentence intelligently
            if len(sentence) > max_chars:
                # Find a good break point
                truncated = sentence[:max_chars]
                # Try to break at punctuation or conjunction
                for bp in ['; ', ', ', ' - ', ' e ', ' ou ']:
                    idx = truncated.rfind(bp)
                    if idx > 40:
                        summary = truncated[:idx+1].strip()
                        break
                else:
                    summary = truncated.rsplit(' ', 1)[0] + "..."
            else:
                summary = sentence
            break

    # Clean up
    summary = summary.strip()
    if summary and not summary[-1] in '.!?':
        if not summary.endswith('...'):
            summary = summary.rstrip(',;:')

    return summary

def main():
    # Load episodes
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episodes.json', 'r', encoding='utf-8') as f:
        episodes = json.load(f)

    print(f"Processing {len(episodes)} episodes...")

    # Enhance each episode
    for i, ep in enumerate(episodes):
        desc = ep.get('description', '')
        title = ep.get('title', '')

        # Generate synthesized summary
        ep['summary'] = synthesize_summary(desc, title)

        # Extract references
        refs = extract_references(desc)
        guest_socials = extract_guest_socials(desc, title)

        # Combine and deduplicate
        all_refs = []
        seen = set()
        for ref in refs + guest_socials:
            ref_lower = ref.lower()
            if ref_lower not in seen:
                seen.add(ref_lower)
                all_refs.append(ref)

        ep['references'] = all_refs

        if (i + 1) % 50 == 0:
            print(f"  Processed {i + 1} episodes...")

    # Save enhanced episodes
    with open('/Users/alastori/Desktop/Naruhodo-transcripts/episodes.json', 'w', encoding='utf-8') as f:
        json.dump(episodes, f, ensure_ascii=False, indent=2)

    print(f"\nEnhanced {len(episodes)} episodes")

    # Print samples
    print("\n=== Sample Enhanced Episodes ===")
    for i in [0, 5, 10, 50, 100]:
        if i < len(episodes):
            ep = episodes[i]
            print(f"\n--- {ep['title'][:60]}... ---")
            print(f"Summary: {ep['summary']}")
            print(f"References: {ep['references'][:3]}...")

if __name__ == '__main__':
    main()
