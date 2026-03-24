# Naruhodo Podcast Transcripts

Scripts and metadata for downloading auto-generated transcripts from the [Naruhodo podcast](http://naruhodo.b9.com.br/) YouTube channel.

## What is Naruhodo?

[Naruhodo](http://naruhodo.b9.com.br/) is a Brazilian Portuguese science podcast hosted by Ken Fujioka (the curious layperson) and Dr. Altay de Souza (the scientist). Each episode explores scientific topics with an accessible, conversational approach.

## What's Included

This repository contains:

- **Scripts**: Python tools to download YouTube auto-captions (`src/`)
- **Episode Metadata**: Titles, dates, summaries, classified references, and more (`data/episodes.json`)
- **Episode Index**: Human-readable catalog (`data/episode-index.md`)

**Not included**: The actual transcript files (`.vtt`). These are downloaded locally using the scripts.

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Installation

```bash
# Clone the repository
git clone https://github.com/alastori/naruhodo-transcripts.git
cd naruhodo-transcripts

# Install dependencies with uv
uv sync

# Or with pip
pip install -e .
```

### Usage

```bash
# Check current status
uv run python -m src.cli status

# Refresh episode metadata from RSS feed
uv run python -m src.cli refresh-index

# Discover YouTube links by matching playlist to RSS episodes
uv run python -m src.cli discover-youtube

# Download transcripts (shows cost estimate first)
uv run python -m src.cli sync

# Skip confirmation prompt
uv run python -m src.cli sync --yes

# Verbose mode (flag goes before subcommand)
uv run python -m src.cli -v sync
```

### Workflow

The typical workflow is:

1. **`refresh-index`** — Fetch episode metadata from the RSS feed
2. **`discover-youtube`** — Match YouTube playlist videos to RSS episodes (populates `youtube_link`)
3. **`sync`** — Download transcripts for episodes with YouTube links

### What the Sync Does

1. **Shows a cost estimate** with expected time and rate limits
2. **Asks for confirmation** before starting
3. **Downloads incrementally** — only new episodes
4. **Handles rate limits** with automatic backoff (waits 1 hour)
5. **Saves progress** — you can Ctrl+C and resume later

## Project Structure

```
naruhodo-transcripts/
├── README.md              # This file
├── LICENSE                # MIT license for code
├── DATA_LICENSE.md        # License info for metadata
├── pyproject.toml         # Python dependencies
├── src/
│   ├── __init__.py
│   ├── cli.py             # Main entry point
│   ├── config.py          # Configuration values
│   ├── downloader.py      # yt-dlp wrapper with retry logic
│   ├── rss_parser.py      # RSS feed parsing & reference classification
│   ├── index_generator.py # Index generation
│   ├── youtube_discovery.py # YouTube link matching
│   └── logging_config.py  # Logging setup
├── data/
│   ├── episodes.json      # Episode metadata (in repo)
│   ├── episode-index.md   # Human-readable index (in repo)
│   └── transcripts/       # Downloaded VTT files (gitignored)
└── tests/                 # Test suite
```

## Data Schema

### episodes.json

Each episode in `data/episodes.json` has the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Episode title from RSS feed |
| `episode_number` | string | Episode number (e.g., "400") or empty |
| `episode_type` | string | `"regular"`, `"interview"`, `"extra"`, or `"other"` |
| `topic` | string | Subject extracted from title (e.g., "Por que gostamos de listas?") |
| `date` | string | Publication date in YYYY-MM-DD format |
| `duration` | string | Episode duration (e.g., "01:23:45") |
| `description` | string | Clean-text episode description |
| `raw_description` | string | Original HTML description from RSS |
| `summary` | string | Synthesized 1-2 sentence summary |
| `guest` | string | Guest name for interview episodes |
| `link` | string | Link to podcast episode page |
| `youtube_link` | string | YouTube video URL for transcript download |
| `guid` | string | RSS feed GUID (stable unique identifier) |
| `audio_url` | string | Direct URL to the MP3 audio file |
| `image_url` | string | Per-episode cover art URL |
| `series` | object\|null | `{"part": N, "total": M}` for multi-part episodes |
| `status` | string | Download status (see below) |
| `references` | array | List of external reference URLs |
| `structured_references` | array | Classified reference objects (see below) |

### Structured References

Each entry in `structured_references` contains:

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Reference URL |
| `domain` | string | Base domain (e.g., "doi.org") |
| `type` | string | Classification (see types below) |
| `label` | string | Human-readable label (e.g., "Paper", "Wiki") |
| `doi` | string | DOI identifier (optional, academic refs only) |
| `pmid` | string | PubMed ID (optional, PubMed refs only) |

**Reference types**: `academic`, `credential`, `thesis`, `social`, `encyclopedia`, `video`, `cross_reference`, `other`

### Status Symbols

| Symbol | Meaning | Description |
|--------|---------|-------------|
| ✅ Downloaded | Transcript available | VTT file exists in `data/transcripts/` |
| ⬜ Pending | Ready to download | Has YouTube link, not yet downloaded |
| 🔗 No Link | Missing YouTube link | Cannot download until link is discovered |

### Example Episode

```json
{
  "title": "Naruhodo #400 - Por que gostamos de listas?",
  "episode_number": "400",
  "episode_type": "regular",
  "topic": "Por que gostamos de listas?",
  "date": "2024-01-15",
  "duration": "01:12:45",
  "description": "Full episode description...",
  "raw_description": "<p>Original HTML description...</p>",
  "summary": "Exploramos a psicologia por trás de nossa fascinação com listas.",
  "guest": "",
  "link": "https://naruhodo.b9.com.br/...",
  "youtube_link": "https://www.youtube.com/watch?v=...",
  "guid": "3897f228-db34-48ab-866d-04dd25f5faba",
  "audio_url": "https://cdn.simplecast.com/audio/...",
  "image_url": "https://image.simplecastcdn.com/images/...",
  "series": null,
  "status": "✅ Downloaded",
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

## Legal Disclaimer

### YouTube Terms of Service

This tool uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to download auto-generated captions from YouTube. While yt-dlp is widely used, be aware that:

- YouTube's Terms of Service technically prohibit automated downloading
- This tool downloads only auto-generated captions (not copyrighted audio/video)
- Use at your own discretion and for personal/research purposes only

### Copyright

- **Podcast content**: The words spoken in the podcast are copyrighted by the Naruhodo creators
- **Auto-generated captions**: Created by Google's ML systems, derived from the audio
- **Episode metadata**: Extracted from publicly available RSS feed (meant for syndication)

### Fair Use Considerations

Downloading transcripts may be defensible under fair use for:
- Personal research and study
- Accessibility purposes
- Educational use
- Text analysis and linguistic research

**This is not legal advice.** If you have concerns, consult a legal professional.

## Attribution

This project is not affiliated with or endorsed by the Naruhodo podcast.

- **Naruhodo Podcast**: http://naruhodo.b9.com.br/
- **Hosts**: Ken Fujioka and Dr. Altay de Souza
- **Support the podcast**: https://orelo.cc/naruhodo

## Contributing

Contributions are welcome! Please open an issue or pull request.

Development setup:

```bash
uv sync
uv run pytest          # run tests
uv run ruff check src/ # lint
```

## License

- **Code**: MIT License (see [LICENSE](LICENSE))
- **Metadata**: See [DATA_LICENSE.md](DATA_LICENSE.md)
