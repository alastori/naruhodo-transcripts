"""Compute actionable transcript quality metrics for episodes.json.

Each episode gets a `transcript_quality` object with 7 fields:
    source:              youtube_vtt | whisper | null
    grade:               A | B | C | null (composite decision)
    word_count:          int | null
    confidence:          float 0-1 | null (Whisper only)
    has_speaker_labels:  bool
    speaker_confidence:  high | medium | low | null
    flags:               list of actionable issue names

Every field maps to a pipeline action:
    source=youtube_vtt     -> naruhodo transcribe --source whisper
    has_speaker_labels=false -> naruhodo diarize
    grade=C                -> prioritize for reprocessing
"""

import json
import re
from pathlib import Path

from .config import (
    EPISODES_JSON,
    KNOWN_SPEAKERS,
    QUALITY_CONFIDENCE_THRESHOLD,
    QUALITY_MAX_WPM,
    QUALITY_MIN_SPEAKER_TURNS,
    QUALITY_MIN_WPM,
    QUALITY_REPEATED_6GRAMS_THRESHOLD,
    TRANSCRIPTS_DIR,
    episode_key,
)


def compute_episode_quality(ep: dict) -> dict:
    """Compute transcript_quality for a single episode.

    Examines the transcript file and quality sidecar on disk.
    Returns the quality dict to be stored in episodes.json.
    """
    key = episode_key(ep)
    if not key or not TRANSCRIPTS_DIR.exists():
        return _empty_quality()

    # Find transcript file
    transcript = _find_transcript_file(key)
    if not transcript:
        return _empty_quality()

    # Determine source
    if transcript.name.endswith(".whisper.md"):
        source = "whisper"
    elif transcript.suffix == ".vtt":
        source = "youtube_vtt"
    else:
        source = "unknown"

    content = transcript.read_text(encoding="utf-8")

    # Word count (deduplicate VTT repeated lines)
    body = _extract_body(content)
    if source == "youtube_vtt":
        # YouTube VTTs repeat every line 2-3x (progressive display)
        lines = body.split("\n")
        seen = set()
        deduped = []
        for line in lines:
            stripped = line.strip()
            if stripped and stripped not in seen:
                seen.add(stripped)
                deduped.append(stripped)
        body = " ".join(deduped)
    word_count = len(body.split())

    # Duration for WPM
    duration_min = _get_duration_min(ep, content)
    wpm = word_count / duration_min if duration_min > 0 else 0

    # Confidence (Whisper only, from quality sidecar)
    confidence = None
    quality_sidecar = transcript.with_suffix(".quality.json")
    if quality_sidecar.exists():
        try:
            data = json.loads(quality_sidecar.read_text())
            confidence = data.get("metrics", {}).get("mean_word_probability")
        except (json.JSONDecodeError, KeyError):
            pass

    # Speaker labels
    has_speaker_labels = any(f"**{s}:**" in content for s in KNOWN_SPEAKERS)

    # Speaker confidence (from diarization header)
    speaker_confidence = None
    if has_speaker_labels:
        conf_match = re.search(r"confidence:\s*(high|medium|low)", content)
        if conf_match:
            speaker_confidence = conf_match.group(1)

    # Flags
    flags = _compute_flags(
        source=source,
        word_count=word_count,
        wpm=wpm,
        confidence=confidence,
        has_speaker_labels=has_speaker_labels,
        content=content,
        duration_min=duration_min,
    )

    # Grade
    grade = _compute_grade(source, confidence, has_speaker_labels, flags)

    return {
        "source": source,
        "grade": grade,
        "word_count": word_count,
        "confidence": round(confidence, 3) if confidence is not None else None,
        "has_speaker_labels": has_speaker_labels,
        "speaker_confidence": speaker_confidence,
        "flags": flags,
    }


def compute_all_quality(episodes: list[dict]) -> list[dict]:
    """Compute transcript_quality for all episodes. Mutates episodes in place."""
    for ep in episodes:
        ep["transcript_quality"] = compute_episode_quality(ep)
    return episodes


def quality_summary(episodes: list[dict]) -> dict:
    """Summarize quality grades across all episodes."""
    grades = {"A": 0, "B": 0, "C": 0, None: 0}
    sources = {"whisper": 0, "youtube_vtt": 0, None: 0}

    for ep in episodes:
        q = ep.get("transcript_quality", {})
        grades[q.get("grade")] = grades.get(q.get("grade"), 0) + 1
        sources[q.get("source")] = sources.get(q.get("source"), 0) + 1

    return {"grades": grades, "sources": sources, "total": len(episodes)}


# --- Private helpers ---


def _empty_quality() -> dict:
    return {
        "source": None,
        "grade": None,
        "word_count": None,
        "confidence": None,
        "has_speaker_labels": False,
        "speaker_confidence": None,
        "flags": [],
    }


def _find_transcript_file(key: str):
    """Find transcript file by episode key, preferring Whisper over VTT."""
    if not TRANSCRIPTS_DIR.exists():
        return None
    prefix = key + " "
    for f in TRANSCRIPTS_DIR.iterdir():
        if f.name.startswith(prefix) and f.name.endswith(".whisper.md"):
            return f
    for f in TRANSCRIPTS_DIR.iterdir():
        if f.name.startswith(prefix) and f.suffix == ".vtt":
            return f
    return None


def _extract_body(content: str) -> str:
    """Extract transcript body text, stripping headers and speaker labels."""
    parts = content.split("---\n")
    body = parts[-1].strip() if len(parts) > 1 else content
    # Strip speaker labels
    body = re.sub(r"\*\*[^*]+:\*\*\s*", "", body)
    # Strip VTT metadata
    body = re.sub(r"WEBVTT.*?\n", "", body)
    body = re.sub(r"\d+:\d+[\d:.]+\s*-->\s*\d+:\d+[\d:.]+\s*", "", body)
    body = re.sub(r"<[^>]+>", "", body)
    return body.strip()


def _get_duration_min(ep: dict, content: str) -> float:
    """Get episode duration in minutes from metadata or transcript header."""
    dur = ep.get("duration", "")
    parts = dur.split(":")
    if len(parts) == 3:
        return int(parts[0]) * 60 + int(parts[1]) + int(parts[2]) / 60
    if len(parts) == 2:
        return int(parts[0]) + int(parts[1]) / 60
    # Fallback: from Whisper header
    m = re.search(r"\*\*Duration:\*\*\s*(\d+):(\d+)", content)
    if m:
        return int(m.group(1)) + int(m.group(2)) / 60
    return 0


def _compute_flags(
    source, word_count, wpm, confidence, has_speaker_labels, content, duration_min,
) -> list:
    flags = []

    if confidence is not None and confidence < QUALITY_CONFIDENCE_THRESHOLD:
        flags.append("low_confidence")

    if duration_min > 5 and word_count < duration_min * QUALITY_MIN_WPM:
        flags.append("incomplete")

    if wpm > QUALITY_MAX_WPM and source != "youtube_vtt":
        # YouTube VTTs have inflated word counts (progressive display repeats)
        flags.append("high_wpm")

    if wpm > 0 and wpm < QUALITY_MIN_WPM:
        flags.append("low_wpm")

    # Repeated n-grams (Whisper only; YouTube VTTs inherently have repeated phrases)
    if source != "youtube_vtt":
        body = _extract_body(content)
        words = body.lower().split()
        if len(words) > 20:
            from collections import Counter
            ngrams = [" ".join(words[i:i+6]) for i in range(len(words) - 5)]
            repeated = sum(1 for c in Counter(ngrams).values() if c > 2)
            if repeated > QUALITY_REPEATED_6GRAMS_THRESHOLD:
                flags.append("repeated_ngrams")

    # Diarization flags
    if has_speaker_labels and duration_min > 15:
        speaker_pat = "|".join(re.escape(s) for s in KNOWN_SPEAKERS)
        turns = len(re.findall(rf"\*\*(?:{speaker_pat}):\*\*", content))
        if turns < QUALITY_MIN_SPEAKER_TURNS:
            flags.append("few_speaker_turns")
        # Check for dominant speaker
        speaker_words = {}
        for line in content.split("\n"):
            m = re.match(r"\*\*(.+?):\*\* (.+)", line)
            if m and m.group(1) in KNOWN_SPEAKERS:
                speaker_words[m.group(1)] = speaker_words.get(m.group(1), 0) + len(m.group(2).split())
        total_sw = sum(speaker_words.values())
        if total_sw > 0 and max(speaker_words.values()) / total_sw > 0.95:
            flags.append("one_speaker_dominant")

    # Intro attribution check
    for line in content.split("\n"):
        m = re.match(r"\*\*(.+?):\*\* (.+)", line)
        if m and m.group(1) in KNOWN_SPEAKERS:
            text = m.group(2).lower()
            if "eu sou ken fujioka" in text:
                if m.group(1) != "Ken Fujioka":
                    flags.append("intro_misattributed")
                break

    return flags


def _compute_grade(source, confidence, has_speaker_labels, flags) -> str:
    """Compute A/B/C grade from quality signals."""
    critical_flags = {"incomplete", "few_speaker_turns", "intro_misattributed", "one_speaker_dominant"}
    has_critical = bool(set(flags) & critical_flags)

    if source == "whisper":
        if confidence is not None and confidence >= QUALITY_CONFIDENCE_THRESHOLD and not has_critical:
            return "A"
        if confidence is not None and confidence >= 0.85 and not has_critical:
            return "B"
        if has_critical or (confidence is not None and confidence < 0.85):
            return "C"
        return "B"  # Whisper without confidence data

    if source == "youtube_vtt":
        if has_speaker_labels and not has_critical:
            return "B"
        return "C"

    return "C"
