# Data Schema

## episodes.json

Each episode in `data/episodes.json` contains:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Episode title from RSS feed |
| `episode_number` | string | Episode number (e.g., "400") or empty |
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
| `series` | object\|null | `{"part": N, "total": M}` for multi-part episodes, null otherwise |
| `references` | array | List of external reference URLs (flat, sponsors and self-references filtered) |
| `structured_references` | array | Classified reference objects (see below) |

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
  ]
}
```
