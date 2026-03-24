# Naruhodo Podcast Transcripts

Scripts and metadata for downloading and generating transcripts from the [Naruhodo podcast](http://naruhodo.b9.com.br/) — a Brazilian Portuguese science podcast hosted by Ken Fujioka and Dr. Altay de Souza.

## What's Included

- **Episode Metadata**: 568 episodes with structured references, topics, and more (`data/episodes.json`)
- **Episode Index**: Human-readable catalog (`data/episode-index.md`)
- **Transcript Tools**: Download YouTube auto-captions or transcribe locally with Whisper

**Not included**: The actual transcript files (`.vtt` / `.md`). You generate them locally using the tools below.

## Quick Start

### Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install and Run

```bash
git clone https://github.com/alastori/naruhodo-transcripts.git
cd naruhodo-transcripts
uv sync

# 1. Fetch episode metadata from RSS feed
uv run naruhodo refresh-index

# 2. Match YouTube videos to episodes
uv run naruhodo discover-youtube

# 3. Download transcripts (YouTube auto-captions)
uv run naruhodo sync
```

That's it. The `sync` command shows a cost estimate, asks for confirmation, handles rate limits automatically, and saves progress so you can Ctrl+C and resume.

### Check Status

```bash
uv run naruhodo status
```

```
📊 Naruhodo Transcript Sync

Current status:
  ├─ Episodes in metadata:       568
  ├─ Transcripts downloaded:     487
  ├─ Pending downloads:          34
  └─ Missing YouTube link:       47
```

## Local Whisper Transcription (Optional)

Some episodes (~47) don't have YouTube links. For these — or for higher-quality transcripts on any episode — you can transcribe directly from the podcast audio using [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon.

### Setup

```bash
# Apple Silicon Mac required (M1/M2/M3/M4)
brew install ffmpeg
uv sync --extra whisper
```

### Usage

```bash
# See what needs transcribing
uv run naruhodo whisper --dry-run

# Transcribe a single episode (test run)
uv run naruhodo whisper --episode 9 --yes

# Transcribe 10 episodes
uv run naruhodo whisper --limit 10 --yes

# Transcribe all missing episodes
uv run naruhodo whisper --yes
```

Whisper transcripts are saved as `.whisper.md` files in `data/transcripts/` and are automatically recognized by `naruhodo status`.

### Speaker Diarization (Optional)

Add speaker labels (Ken Fujioka vs Altay de Souza) using [pyannote](https://github.com/pyannote/pyannote-audio) for speaker detection and [Ollama](https://ollama.com) for speaker identification:

```bash
# Install diarization dependencies
uv sync --extra diarize

# Accept gated model terms (free, one-time):
#   https://huggingface.co/pyannote/speaker-diarization-3.1
#   https://huggingface.co/pyannote/segmentation-3.0

# Set your HuggingFace token
export HF_TOKEN="hf_your_token_here"

# Pull an Ollama model for speaker identification
ollama pull qwen2.5:72b-instruct-q4_K_M

# Transcribe with diarization
uv run naruhodo whisper --diarize --episode 9 --yes
```

The output labels each paragraph with the speaker name:

```markdown
**Altay de Souza:** Neste episódio vamos falar sobre...

**Ken Fujioka:** E como é que isso funciona?

**Altay de Souza:** Então, a ciência mostra que...
```

## All Commands

| Command | Description |
|---------|-------------|
| `naruhodo status` | Show current sync status and cost estimates |
| `naruhodo refresh-index` | Refresh episode metadata from RSS feed |
| `naruhodo discover-youtube` | Match YouTube playlist videos to RSS episodes |
| `naruhodo sync` | Download YouTube auto-captions (fast, default) |
| `naruhodo whisper` | Transcribe locally with MLX Whisper (high quality) |
| `naruhodo whisper --diarize` | Transcribe with speaker labels |

Use `-v` before the subcommand for verbose output. Most commands accept `--help` for details.

## Data Schema

### episodes.json

Each episode in `data/episodes.json` has the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `title` | string | Episode title from RSS feed |
| `episode_number` | string | Episode number (e.g., "400") or empty |
| `episode_type` | string | `"regular"`, `"interview"`, `"extra"`, or `"other"` |
| `topic` | string | Subject extracted from title |
| `date` | string | Publication date (YYYY-MM-DD) |
| `duration` | string | Episode duration (HH:MM:SS) |
| `description` | string | Clean-text episode description |
| `raw_description` | string | Original HTML description from RSS |
| `summary` | string | Synthesized 1-2 sentence summary |
| `guest` | string | Guest name for interview episodes |
| `link` | string | Podcast episode page URL |
| `youtube_link` | string | YouTube video URL |
| `guid` | string | RSS feed GUID (stable unique identifier) |
| `audio_url` | string | Direct URL to the MP3 audio file |
| `image_url` | string | Per-episode cover art URL |
| `series` | object\|null | `{"part": N, "total": M}` for multi-part episodes |
| `status` | string | Download status emoji |
| `references` | array | List of external reference URLs |
| `structured_references` | array | Classified reference objects (see below) |

### Structured References

Each entry in `structured_references`:

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Reference URL |
| `domain` | string | Base domain |
| `type` | string | `academic`, `credential`, `thesis`, `social`, `encyclopedia`, `video`, `cross_reference`, `other` |
| `label` | string | Human-readable label (e.g., "Paper", "Wiki") |
| `doi` | string | DOI identifier (academic refs only, optional) |
| `pmid` | string | PubMed ID (optional) |

## Legal Disclaimer

### YouTube Terms of Service

This tool uses [yt-dlp](https://github.com/yt-dlp/yt-dlp) to download auto-generated captions from YouTube. While yt-dlp is widely used, be aware that:

- YouTube's Terms of Service technically prohibit automated downloading
- This tool downloads only auto-generated captions (not copyrighted audio/video)
- Use at your own discretion and for personal/research purposes only

### Copyright

- **Podcast content**: Copyrighted by the Naruhodo creators
- **Auto-generated captions**: Created by Google's ML systems
- **Episode metadata**: Extracted from publicly available RSS feed

### Fair Use

Downloading transcripts may be defensible under fair use for personal research, accessibility, educational use, and text analysis.

**This is not legal advice.**

## Attribution

This project is not affiliated with or endorsed by the Naruhodo podcast.

- **Naruhodo Podcast**: http://naruhodo.b9.com.br/
- **Hosts**: Ken Fujioka and Dr. Altay de Souza
- **Support the podcast**: https://orelo.cc/naruhodo or https://www.patreon.com/naruhodopodcast

## Contributing

Contributions are welcome! Please open an issue or pull request.

```bash
uv sync --extra dev
uv run pytest         # run tests
uv run ruff check src # lint
```

## License

- **Code**: MIT License (see [LICENSE](LICENSE))
- **Metadata**: See [DATA_LICENSE.md](DATA_LICENSE.md)
