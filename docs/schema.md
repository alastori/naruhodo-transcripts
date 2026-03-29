# Data Schema

~570 episodes, ~7 MB, UTF-8 encoded.

```python
import json
episodes = json.load(open("data/episodes.json"))
print(f"{len(episodes)} episodes")
```

```bash
# jq: list all episode titles
jq '.[].title' data/episodes.json
```

## episodes.json

Each episode in `data/episodes.json` contains:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Episode title from RSS feed |
| `episode_number` | string | Episode number (e.g., "400") or empty. String because some are empty for unnumbered episodes. |
| `episode_type` | string | `"regular"`, `"interview"`, `"extra"`, or `"other"` |
| `topic` | string | Subject extracted from title |
| `date` | string | Publication date (YYYY-MM-DD) |
| `duration` | string | Episode duration (HH:MM:SS) |
| `description` | string | Clean-text episode description |
| `raw_description` | string | Original HTML description from RSS (for researchers needing full show notes with formatting) |
| `summary` | string | Synthesized 1-2 sentence summary |
| `guest` | string | Guest name for interview episodes |
| `link` | string | Podcast episode page URL |
| `youtube_link` | string | YouTube video URL |
| `guid` | string | RSS feed GUID (stable unique identifier, used as merge key) |
| `audio_url` | string | Direct URL to the MP3 audio file (from RSS enclosure) |
| `image_url` | string | Per-episode cover art URL |
| `series` | object\|null | `{"part": N, "total": M}` for multi-part episodes (same topic across episodes), null otherwise |
| `references` | array | List of external reference URLs (flat, sponsors and self-references filtered) |
| `structured_references` | array | Classified reference objects (see below) |
| `transcript_quality` | object\|null | Quality metrics and grade (see below) |

## Structured References

Each entry in the `structured_references` array:

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Reference URL |
| `domain` | string | Base domain (www stripped) |
| `type` | string | Classification (see types below) |
| `label` | string | Human-readable label (e.g., "Paper", "Wiki") |
| `doi` | string | DOI identifier (optional, academic refs only) |
| `pmid` | string | PubMed ID (optional) |

### Reference Types

| Type | Description | Examples |
|------|-------------|----------|
| `academic` | Papers, journals, preprints | doi.org, sciencedirect.com, nature.com, pubmed |
| `cross_reference` | Other Naruhodo episodes or B9 network | naruhodo.b9.com.br, b9.com.br |
| `video` | YouTube videos | youtube.com |
| `book` | Book references | books.google.com, amazon.com |
| `podcast` | Audio platforms | open.spotify.com, anchor.fm |
| `credential` | Researcher profiles | lattes.cnpq.br, orcid.org |
| `social` | Social media | twitter.com, instagram.com |
| `encyclopedia` | Knowledge bases | wikipedia.org, plato.stanford.edu |
| `thesis` | Academic theses | teses.usp.br |
| `other` | Unclassified | Blogs, news, government sites |

## Transcript Quality

Each episode's `transcript_quality` object:

| Field | Type | Values | What to do |
|-------|------|--------|------------|
| `source` | string\|null | `"youtube_vtt"`, `"whisper"` | YouTube = low quality text. Upgrade with `naruhodo transcribe --source whisper` |
| `grade` | string\|null | `"A"`, `"B"`, `"C"` | A = good. B = usable. C = re-process recommended |
| `word_count` | int\|null | | Check against duration for completeness |
| `confidence` | float\|null | 0.0-1.0 (Whisper only) | Below 0.90 = re-transcribe |
| `has_speaker_labels` | bool | | false = run `naruhodo diarize` |
| `speaker_confidence` | string\|null | `"high"`, `"medium"`, `"low"` | low = re-diarize with `--force` |
| `flags` | array | see below | Each flag implies a specific fix |

**Grades:** A = Whisper + confidence >= 0.90 + no critical flags. B = Whisper with minor issues, or YouTube VTT with speaker labels. C = YouTube VTT without labels, or low confidence, or critical flags.

**Flags:** `low_confidence`, `incomplete`, `repeated_ngrams`, `few_speaker_turns`, `one_speaker_dominant`, `intro_misattributed`, `high_wpm`, `low_wpm`

## Example Episode

```json
{
  "title": "Naruhodo #400 - Por que gostamos de listas?",
  "episode_number": "400",
  "episode_type": "regular",
  "topic": "Por que gostamos de listas?",
  "date": "2024-01-15",
  "duration": "01:12:45",
  "description": "Full episode description...",
  "raw_description": "<p>Original HTML description from RSS...</p>",
  "summary": "Exploramos a psicologia por trás de nossa fascinação com listas.",
  "guest": "",
  "link": "https://naruhodo.b9.com.br/...",
  "youtube_link": "https://www.youtube.com/watch?v=...",
  "guid": "3897f228-db34-48ab-866d-04dd25f5faba",
  "audio_url": "https://cdn.simplecast.com/audio/...",
  "image_url": "https://image.simplecastcdn.com/images/...",
  "series": null,
  "references": [
    "https://doi.org/10.1000/example"
  ],
  "structured_references": [
    {
      "url": "https://doi.org/10.1000/example",
      "domain": "doi.org",
      "type": "academic",
      "label": "Paper",
      "doi": "10.1000/example"
    }
  ],
  "transcript_quality": {
    "source": "whisper",
    "grade": "A",
    "word_count": 10236,
    "confidence": 0.955,
    "has_speaker_labels": true,
    "speaker_confidence": "high",
    "flags": []
  }
}
```
