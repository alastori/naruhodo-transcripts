# Naruhodo Podcast Transcripts

CLI toolkit and curated metadata for the [Naruhodo podcast](http://naruhodo.b9.com.br/) (Brazilian Portuguese, science). Download YouTube auto-captions or transcribe locally with Whisper. Useful for accessibility, language study, or text analysis.

## Quick Start

```bash
git clone https://github.com/alastori/naruhodo-transcripts.git
cd naruhodo-transcripts
uv sync    # Python 3.10+, uv (https://docs.astral.sh/uv/)

naruhodo catalog      # fetch episode metadata + match YouTube links
naruhodo transcribe   # get transcripts (YouTube captions, Whisper fallback)
naruhodo status       # see what you have
```

## Pipeline

Three stages, each incremental and self-validating:

```
catalog → transcribe → diarize
              ↑            │
              └── review flagged, reprocess as needed
```

| Stage | What it does | Rerun behavior |
|-------|-------------|----------------|
| `catalog` | Fetch RSS metadata, match YouTube links | Only fetches new episodes |
| `transcribe` | Get transcripts (YouTube or Whisper) | Only processes missing episodes |
| `diarize` | Add speaker labels (Ken vs Altay) | Only processes unlabeled transcripts |

Each stage reports quality metrics and flags suspect episodes. Run `naruhodo status` for the full dashboard.

### Transcribe

```bash
naruhodo transcribe                          # auto: YouTube when available, Whisper fallback
naruhodo transcribe --source youtube         # YouTube captions only
naruhodo transcribe --source whisper         # Whisper only (Apple Silicon, brew install ffmpeg)
naruhodo transcribe --episode 400            # specific episode
naruhodo transcribe --dry-run                # preview without running
```

Whisper requires `uv sync --extra whisper`. See `naruhodo transcribe --help` for all options.

### Diarize

```bash
naruhodo diarize                             # label all unlabeled transcripts
naruhodo diarize --episode 400               # specific episode
naruhodo diarize --llm claude:sonnet         # use Claude for speaker ID
naruhodo diarize --force                     # re-diarize already labeled transcripts
```

Requires `uv sync --extra diarize` and a HuggingFace token. See [docs/diarization-setup.md](docs/diarization-setup.md).

### Status

```bash
naruhodo status
```

```
📊 Naruhodo Pipeline Status

  Catalog:     568 episodes
               514 with YouTube link, 54 without

  Transcribe:  568/568 with transcript
               487 YouTube VTT, 81 Whisper
               ⚠️  3 flagged (low confidence)

  Diarize:     78/81 Whisper transcripts with speaker labels
               ⚠️  2 flagged (low turn count)

  Next: review flagged episodes
```

## Reference

- [Data Schema](docs/schema.md) - `episodes.json` fields, structured reference types
- [Diarization Setup](docs/diarization-setup.md) - HuggingFace, LLM configuration
- [Data License](DATA_LICENSE.md) - Licensing, usage terms, fair-use guidance

## Attribution

Not affiliated with the Naruhodo podcast. **Support them**: [Orelo](https://orelo.cc/naruhodo) | [Patreon](https://www.patreon.com/naruhodopodcast)

## License

Code: [MIT](LICENSE) | Metadata: [CC BY-NC 4.0](DATA_LICENSE.md)
