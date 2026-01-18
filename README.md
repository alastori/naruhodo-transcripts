# Naruhodo Podcast Transcripts

Scripts and metadata for downloading auto-generated transcripts from the [Naruhodo podcast](http://naruhodo.b9.com.br/) YouTube channel.

## What is Naruhodo?

[Naruhodo](http://naruhodo.b9.com.br/) is a Brazilian Portuguese science podcast hosted by Ken Fujioka (the curious layperson) and Dr. Altay de Souza (the scientist). Each episode explores scientific topics with an accessible, conversational approach.

## What's Included

This repository contains:

- **Scripts**: Python tools to download YouTube auto-captions (`src/`)
- **Episode Metadata**: Titles, dates, summaries, and references (`data/episodes.json`)
- **Episode Index**: Human-readable catalog (`data/episode-index.md`)

**Not included**: The actual transcript files (`.vtt`). These are downloaded locally using the scripts.

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/naruhodo-transcripts.git
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

# Download transcripts (shows cost estimate first)
uv run python -m src.cli sync

# Skip confirmation prompt
uv run python -m src.cli sync --yes

# Verbose mode
uv run python -m src.cli sync -v
```

### What the Sync Does

1. **Shows a cost estimate** with expected time and rate limits
2. **Asks for confirmation** before starting
3. **Downloads incrementally** - only new episodes
4. **Handles rate limits** with automatic backoff (waits 1 hour)
5. **Saves progress** - you can Ctrl+C and resume later

Example output:
```
📊 Naruhodo Transcript Sync

Current status:
  ├─ Episodes in metadata:       558
  ├─ Transcripts downloaded:     487
  └─ Pending with YouTube link:  71

Estimated cost:
  ├─ YouTube API requests:     71
  ├─ Download time:            ~4 minutes (at 3s/request)
  ├─ Expected rate limits:     ~1 (every ~60 requests)
  ├─ Rate limit wait time:     ~1 hours (1h per limit)
  └─ Total estimated time:     1.1 hours

⚠️  YouTube may rate-limit after ~60 requests.
    The script will automatically retry with exponential backoff.
    You can safely Ctrl+C and resume later - progress is saved.

Proceed? [y/N]:
```

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
│   ├── rss_parser.py      # RSS feed parsing
│   ├── index_generator.py # Index generation
│   ├── youtube_discovery.py # YouTube link matching
│   └── logging_config.py  # Logging setup
├── data/
│   ├── episodes.json      # Episode metadata (in repo)
│   ├── episode-index.md   # Human-readable index (in repo)
│   └── transcripts/       # Downloaded VTT files (gitignored)
└── temp/
    └── logs/              # Download logs (gitignored)
```

## Data Schema

### episodes.json

Each episode in `data/episodes.json` has the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Episode title from RSS feed |
| `episode_number` | string | Episode number (e.g., "400") or empty if not applicable |
| `date` | string | Publication date in YYYY-MM-DD format |
| `duration` | string | Episode duration (e.g., "01:23:45" or "45:30") |
| `description` | string | Full episode description from RSS |
| `summary` | string | Synthesized 1-2 sentence summary |
| `guest` | string | Guest name for interview episodes |
| `link` | string | Link to podcast episode page |
| `youtube_link` | string | YouTube video URL for transcript download |
| `status` | string | Download status (see below) |
| `references` | array | List of reference URLs from description |

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
  "date": "2024-01-15",
  "duration": "01:12:45",
  "description": "Full episode description...",
  "summary": "Exploramos a psicologia por trás de nossa fascinação com listas.",
  "guest": "",
  "link": "https://naruhodo.b9.com.br/...",
  "youtube_link": "https://www.youtube.com/watch?v=...",
  "status": "✅ Downloaded",
  "references": [
    "https://doi.org/10.1000/example"
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

## License

- **Code**: MIT License (see [LICENSE](LICENSE))
- **Metadata**: See [DATA_LICENSE.md](DATA_LICENSE.md)
