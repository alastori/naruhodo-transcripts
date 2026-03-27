# Naruhodo Podcast Transcripts

Searchable text transcripts for every episode of the [Naruhodo podcast](http://naruhodo.b9.com.br/) (Brazilian Portuguese, science).

Most transcripts come from YouTube's automatic subtitles (the podcast publishes video versions of many episodes). For episodes without a YouTube video, the toolkit generates transcripts locally using [Whisper](https://github.com/openai/whisper), an open-source speech-to-text model from OpenAI.

A third, optional stage, **speaker labeling** ("diarization"), marks which lines were spoken by hosts Ken Fujioka and Altay de Souza, so you can tell who said what. Useful for accessibility, language study, or text analysis.

## Data

Episode metadata lives in `data/episodes.json` (one entry per episode with title, date, duration, topic, classified academic references, and more). Transcripts are stored as individual text files under `data/transcripts/`.

See **[Data Schema](docs/schema.md)** for the full field reference and a sample JSON entry.

## Prerequisites

> **Required**
>
> - **Python 3.10** or newer (`python3 --version`)
> - **[uv](https://docs.astral.sh/uv/)** package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
>
> **Optional**, for local speech-to-text with Whisper:
> - Apple Silicon Mac (M1 or newer)
> - ffmpeg (`brew install ffmpeg`)

## Quick Start

```bash
git clone https://github.com/alastori/naruhodo-transcripts.git
cd naruhodo-transcripts
uv sync

naruhodo catalog
naruhodo transcribe
naruhodo status
```

**What these commands do:**

1. **`catalog`** downloads the podcast's RSS feed and builds `data/episodes.json` with metadata for every episode. It also finds the matching YouTube video for each episode.

2. **`transcribe`** gets a transcript for each episode. It tries YouTube's automatic subtitles first; if no YouTube video exists, it falls back to generating a transcript locally using Whisper (requires extra setup above).

3. **`status`** prints a dashboard showing how many episodes have been cataloged, transcribed, and speaker-labeled, and flags any that need review.

## Pipeline

Three stages, each incremental. Run them again anytime; they only process what's new.

| Stage | What it does | On rerun |
|-------|-------------|----------|
| `catalog` | Fetch the podcast feed and build the episode list | Skips known episodes |
| `transcribe` | Download YouTube subtitles, or generate from audio with Whisper | Skips episodes that already have transcripts |
| `diarize` | Label who is speaking (Ken or Altay) at each point | Skips already-labeled transcripts |

### Transcribe

```bash
naruhodo transcribe                          # auto: YouTube first, Whisper fallback
naruhodo transcribe --source youtube         # YouTube subtitles only
naruhodo transcribe --source whisper         # local speech-to-text (requires setup above)
naruhodo transcribe --episode 400            # specific episode
naruhodo transcribe --dry-run                # preview without running
```

Whisper requires: `uv sync --extra whisper`. See `naruhodo transcribe --help` for model selection.

### Speaker Labeling (Diarize)

Naruhodo is a conversation between two hosts. The diarize stage figures out who said each line and adds their name to the transcript:

> Before: *And that's exactly what the research shows. But wait, there's a second experiment...*
>
> After:
> **Altay de Souza:** And that's exactly what the research shows.
> **Ken Fujioka:** But wait, there's a second experiment...

```bash
naruhodo diarize                             # label all unlabeled transcripts
naruhodo diarize --episode 400               # specific episode
naruhodo diarize --llm claude:sonnet         # use Claude for speaker identification
naruhodo diarize --force                     # re-label already labeled transcripts
```

Requires extra setup: `uv sync --extra diarize` and a free HuggingFace account. See [Speaker Labeling Setup](docs/diarization-setup.md).

### Status

```bash
naruhodo status
```

```
Naruhodo Pipeline Status

  Catalog:     568 episodes
  Transcribe:  568/568 with transcript (487 YouTube, 81 Whisper)
  Diarize:     78/81 Whisper transcripts with speaker labels
               2 flagged (low turn count)

  Next: review flagged episodes
```

## Reference

- [Data Schema](docs/schema.md) - `episodes.json` fields, reference types
- [Speaker Labeling Setup](docs/diarization-setup.md) - HuggingFace, LLM configuration
- [Data License](DATA_LICENSE.md) - Licensing, usage terms

## Attribution

Not affiliated with the Naruhodo podcast. **Support them**: [Orelo](https://orelo.cc/naruhodo) | [Patreon](https://www.patreon.com/naruhodopodcast)

## License

Code: [MIT](LICENSE) | Metadata: [CC BY-NC 4.0](DATA_LICENSE.md)
