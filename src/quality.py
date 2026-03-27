"""Quality check for Naruhodo podcast transcripts.

Analyzes transcript quality across multiple tiers:
  Tier 1: Whisper confidence signals (from .quality.json sidecars)
  Tier 2: Per-episode aggregate metrics
  Tier 3: Cross-validation (YouTube VTT vs Whisper, requires jiwer)
  Tier 4: LLM spot-check on flagged episodes
"""

import json
import re
from collections import Counter
from pathlib import Path

from .config import (
    DATA_DIR,
    EPISODES_JSON,
    KNOWN_SPEAKERS,
    QUALITY_MEAN_LOGPROB_THRESHOLD,
    QUALITY_MIN_SPEAKER_TURNS,
    QUALITY_REPEATED_6GRAMS_THRESHOLD,
    TRANSCRIPTS_DIR,
)
from .rss_parser import load_episodes as _canonical_load_episodes


def load_episodes_by_number() -> dict[str, dict]:
    """Load episodes keyed by episode number, excluding replays.

    Delegates to the canonical load_episodes from rss_parser for safe loading,
    then indexes by episode number.
    """
    episodes = _canonical_load_episodes(EPISODES_JSON)
    by_num = {}
    for ep in episodes:
        num = ep.get("episode_number", "")
        if num and "REPLAY" not in ep.get("title", ""):
            by_num[num] = ep
    return by_num


# --- Tier 1: Whisper quality signals ---


def tier1_whisper_signals():
    """Analyze quality signals from .quality.json sidecar files."""
    quality_files = list(TRANSCRIPTS_DIR.glob("*.quality.json"))
    if not quality_files:
        print("No .quality.json files found. Run whisper transcription first.")
        return []

    results = []
    for f in sorted(quality_files):
        data = json.loads(f.read_text())
        m = data.get("metrics", {})
        ep_match = re.search(r"#(\d+)", data.get("episode", ""))
        ep_num = ep_match.group(1) if ep_match else "?"

        flags = []
        if m.get("mean_logprob", 0) < QUALITY_MEAN_LOGPROB_THRESHOLD:
            flags.append("low_confidence")
        if m.get("high_compression_segments", 0) > len(quality_files) * 0.1:
            flags.append("possible_hallucination")
        if m.get("repeated_6grams", 0) > QUALITY_REPEATED_6GRAMS_THRESHOLD:
            flags.append(f"repeated_ngrams({m['repeated_6grams']})")
        if m.get("words_per_minute", 150) < 100:
            flags.append("low_wpm")
        if m.get("words_per_minute", 150) > 220:
            flags.append("high_wpm")
        if m.get("fallback_segments", 0) > 5:
            flags.append(f"temp_fallbacks({m['fallback_segments']})")

        results.append({
            "episode": ep_num,
            "file": f.name,
            "metrics": m,
            "flags": flags,
        })

    return results


# --- Tier 2: Per-episode aggregate metrics ---


def tier2_episode_metrics():
    """Compute per-episode metrics from transcript files."""
    results = []

    for f in sorted(TRANSCRIPTS_DIR.glob("*.whisper.md")):
        if "REPLAY" in f.name or "REPOST" in f.name:
            continue

        content = f.read_text()
        ep_match = re.search(r"#(\d+)", f.name)
        ep_num = ep_match.group(1) if ep_match else "?"

        # Extract transcript body
        parts = content.split("---\n")
        body = parts[-1].strip() if len(parts) > 1 else content

        # Word count
        words = body.split()
        word_count = len(words)

        # Speaker analysis
        speaker_words = {}
        speaker_segments = {}
        for line in content.split("\n"):
            m = re.match(r"\*\*(.+?):\*\* (.+)", line)
            if m and m.group(1) in KNOWN_SPEAKERS:
                name = m.group(1)
                w = len(m.group(2).split())
                speaker_words[name] = speaker_words.get(name, 0) + w
                speaker_segments[name] = speaker_segments.get(name, 0) + 1

        total_speaker_words = sum(speaker_words.values())
        total_segments = sum(speaker_segments.values())

        # Speaker balance
        if total_speaker_words > 0:
            dominant_pct = max(speaker_words.values()) / total_speaker_words * 100
        else:
            dominant_pct = 0

        # Intro attribution check
        intro_ok = _check_intro_attribution(content)

        # Type-token ratio
        lower_words = [w.lower() for w in words if len(w) > 2]
        ttr = len(set(lower_words)) / len(lower_words) if lower_words else 0

        # Duration from header
        dur_match = re.search(r"\*\*Duration:\*\* (\d+):(\d+)", content)
        duration_min = 0
        if dur_match:
            duration_min = int(dur_match.group(1)) + int(dur_match.group(2)) / 60
        wpm = word_count / duration_min if duration_min > 0 else 0

        # Flags
        flags = []
        if dominant_pct > 95 and total_segments > 0:
            flags.append("one_speaker_dominant")
        if total_segments < QUALITY_MIN_SPEAKER_TURNS and duration_min > 20:
            flags.append("few_speaker_turns")
        if intro_ok == False:  # noqa: E712 (explicit False, not None)
            flags.append("intro_misattributed")
        if wpm < 100:
            flags.append("low_wpm")
        if wpm > 220:
            flags.append("high_wpm")
        if ttr < 0.15:
            flags.append("low_vocabulary")

        results.append({
            "episode": ep_num,
            "word_count": word_count,
            "duration_min": round(duration_min, 1),
            "wpm": round(wpm, 1),
            "speaker_segments": total_segments,
            "dominant_speaker_pct": round(dominant_pct, 1),
            "ttr": round(ttr, 3),
            "intro_ok": intro_ok,
            "flags": flags,
        })

    return results


def _check_intro_attribution(content: str):  # -> bool | None
    """Check if 'Eu sou Ken Fujioka' is attributed to Ken (not Altay).

    Returns True (correct), False (wrong), or None (not found).
    """
    for line in content.split("\n"):
        m = re.match(r"\*\*(.+?):\*\* (.+)", line)
        if m and m.group(1) in KNOWN_SPEAKERS:
            text = m.group(2).lower()
            if "eu sou ken fujioka" in text and "eu sou altay" in text:
                # Both intros in one block means diarization lumped them
                speaker = m.group(1)
                return speaker == "Ken Fujioka"
            if "eu sou ken fujioka" in text:
                return m.group(1) == "Ken Fujioka"
            if "eu sou altay" in text or "eu sou o altay" in text:
                return m.group(1) == "Altay de Souza"
    return None


# --- Tier 3: Cross-validation ---


def tier3_cross_validate():
    """Compare YouTube VTT vs Whisper transcripts using WER."""
    try:
        import jiwer
    except ImportError:
        print("jiwer not installed. Run: pip install jiwer")
        return []

    results = []

    for whisper_file in sorted(TRANSCRIPTS_DIR.glob("*.whisper.md")):
        ep_match = re.search(r"#(\d+)", whisper_file.name)
        if not ep_match:
            continue
        ep_num = ep_match.group(1)

        # Find matching VTT
        vtt_files = [
            f for f in TRANSCRIPTS_DIR.glob("*.vtt")
            if f"Naruhodo #{ep_num} " in f.name or f"Naruhodo #{ep_num} " in f.name.replace("\uff1a", ":")
        ]
        if not vtt_files:
            continue

        # Extract text from both
        whisper_text = _extract_whisper_text(whisper_file)
        vtt_text = _extract_vtt_text(vtt_files[0])

        if not whisper_text or not vtt_text:
            continue

        # Compute WER
        wer = jiwer.wer(vtt_text, whisper_text)
        cer = jiwer.cer(vtt_text, whisper_text)

        flags = []
        if wer > 0.4:
            flags.append("high_wer")
        if wer > 0.6:
            flags.append("very_high_wer")

        results.append({
            "episode": ep_num,
            "wer": round(wer, 3),
            "cer": round(cer, 3),
            "whisper_words": len(whisper_text.split()),
            "vtt_words": len(vtt_text.split()),
            "flags": flags,
        })

    return results


def _extract_whisper_text(path: Path) -> str:
    """Extract plain text from a .whisper.md file."""
    content = path.read_text()
    parts = content.split("---\n")
    body = parts[-1].strip() if len(parts) > 1 else ""
    # Strip speaker labels
    lines = []
    for line in body.split("\n"):
        m = re.match(r"\*\*.+?:\*\* (.+)", line)
        if m:
            lines.append(m.group(1))
        elif line.strip():
            lines.append(line.strip())
    return " ".join(lines)


def _extract_vtt_text(path: Path) -> str:
    """Extract plain text from a .vtt file, stripping timestamps and tags."""
    content = path.read_text(errors="replace")
    lines = []
    for line in content.split("\n"):
        line = line.strip()
        if not line or line == "WEBVTT":
            continue
        if "-->" in line:
            continue
        if line.startswith("Kind:") or line.startswith("Language:") or line.startswith("NOTE"):
            continue
        if re.match(r"^\d+$", line):
            continue
        # Strip VTT tags
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            lines.append(clean)
    # Deduplicate consecutive identical lines (YouTube VTT pattern)
    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return " ".join(deduped)


# --- Tier 4: LLM spot-check ---


def tier4_llm_check(episodes_to_check: list[str], llm_spec: str = "claude:sonnet"):
    """Run LLM quality check on specific episodes."""
    from .llm import llm_call, load_prompt

    results = []
    for ep_num in episodes_to_check:
        whisper_files = [
            f for f in TRANSCRIPTS_DIR.glob("*.whisper.md")
            if f"#{ep_num} " in f.name and "REPLAY" not in f.name
        ]
        if not whisper_files:
            continue

        content = whisper_files[0].read_text()
        # Truncate to ~3000 words for LLM
        parts = content.split("---\n")
        body = parts[-1].strip() if len(parts) > 1 else content
        words = body.split()
        truncated = " ".join(words[:3000])

        try:
            prompt = load_prompt("diarization_quality_check", transcript=truncated)
            result = llm_call(llm_spec, prompt, timeout=120)
            result["episode"] = ep_num
            results.append(result)
            quality = result.get("quality", "?")
            print(f"  #{ep_num}: {quality}", flush=True)
        except Exception as e:
            print(f"  #{ep_num}: LLM check failed: {e}", flush=True)
            results.append({"episode": ep_num, "quality": "error", "error": str(e)})

    return results


# --- Reporting ---


def print_report(tier1, tier2, tier3, tier4):
    """Print a consolidated quality report."""
    print("\n" + "=" * 60)
    print("TRANSCRIPT QUALITY REPORT")
    print("=" * 60)

    if tier1:
        flagged = [r for r in tier1 if r["flags"]]
        print(f"\n--- Tier 1: Whisper Signals ({len(tier1)} episodes) ---")
        print(f"  Clean: {len(tier1) - len(flagged)}")
        print(f"  Flagged: {len(flagged)}")
        if flagged:
            # Count flag types
            flag_counts = Counter()
            for r in flagged:
                for f in r["flags"]:
                    flag_counts[f.split("(")[0]] += 1
            for flag, count in flag_counts.most_common():
                print(f"    {flag}: {count}")

    if tier2:
        flagged = [r for r in tier2 if r["flags"]]
        print(f"\n--- Tier 2: Episode Metrics ({len(tier2)} episodes) ---")
        print(f"  Clean: {len(tier2) - len(flagged)}")
        print(f"  Flagged: {len(flagged)}")

        if flagged:
            flag_counts = Counter()
            for r in flagged:
                for f in r["flags"]:
                    flag_counts[f] += 1
            for flag, count in flag_counts.most_common():
                print(f"    {flag}: {count}")
            print(f"\n  Worst episodes:")
            worst = sorted(flagged, key=lambda r: -len(r["flags"]))[:10]
            for r in worst:
                print(f"    #{r['episode']:>4}: {', '.join(r['flags'])}")

        # Corpus stats
        wpm_vals = [r["wpm"] for r in tier2 if r["wpm"] > 0]
        if wpm_vals:
            print(f"\n  WPM: min={min(wpm_vals):.0f} median={sorted(wpm_vals)[len(wpm_vals)//2]:.0f} max={max(wpm_vals):.0f}")

        intro_stats = Counter(r["intro_ok"] for r in tier2)
        print(f"  Intro attribution: correct={intro_stats.get(True,0)} wrong={intro_stats.get(False,0)} not_found={intro_stats.get(None,0)}")

    if tier3:
        print(f"\n--- Tier 3: Cross-Validation ({len(tier3)} episodes) ---")
        wers = [r["wer"] for r in tier3]
        flagged = [r for r in tier3 if r["flags"]]
        print(f"  Mean WER: {sum(wers)/len(wers):.1%}")
        print(f"  Median WER: {sorted(wers)[len(wers)//2]:.1%}")
        print(f"  Flagged (>40% WER): {len(flagged)}")
        if flagged:
            for r in sorted(flagged, key=lambda r: -r["wer"])[:5]:
                print(f"    #{r['episode']}: WER={r['wer']:.1%} (whisper={r['whisper_words']}w, vtt={r['vtt_words']}w)")

    if tier4:
        print(f"\n--- Tier 4: LLM Spot-Check ({len(tier4)} episodes) ---")
        for r in tier4:
            quality = r.get("quality", "?")
            issues = r.get("issues", [])
            print(f"  #{r['episode']}: {quality}", end="")
            if issues:
                print(f" - {'; '.join(issues[:3])}")
            else:
                print()


def run_quality_check(
    tier=None,
    cross_validate=False,
    llm_check=0,
    llm_spec="claude:sonnet",
    episode=None,
    as_json=False,
) -> int:
    """Run quality checks. Called from CLI."""
    tier1 = tier2 = tier3 = tier4 = []

    if episode:
        tier2 = tier2_episode_metrics()
        tier2 = [r for r in tier2 if r["episode"] == episode]
        if tier2:
            print(json.dumps(tier2[0], indent=2))
        else:
            print(f"Episode #{episode} not found in whisper transcripts")
        return 0

    if tier in (None, 1):
        tier1 = tier1_whisper_signals()
    if tier in (None, 2):
        tier2 = tier2_episode_metrics()
    if tier == 3 or cross_validate:
        tier3 = tier3_cross_validate()
    if tier == 4 or llm_check:
        if not tier2:
            tier2 = tier2_episode_metrics()
        flagged = sorted(
            [r for r in tier2 if r["flags"]],
            key=lambda r: -len(r["flags"]),
        )
        n = llm_check or 5
        episodes = [r["episode"] for r in flagged[:n]]
        if episodes:
            print(f"Running LLM check on {len(episodes)} flagged episodes...")
            tier4 = tier4_llm_check(episodes, llm_spec)
        else:
            print("No flagged episodes to check.")

    if as_json:
        print(json.dumps({
            "tier1": tier1, "tier2": tier2, "tier3": tier3, "tier4": tier4,
        }, indent=2, ensure_ascii=False))
    else:
        print_report(tier1, tier2, tier3, tier4)

    return 0
