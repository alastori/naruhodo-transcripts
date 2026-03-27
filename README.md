# Naruhodo Podcast Transcripts

CLI toolkit and curated metadata for the [Naruhodo podcast](http://naruhodo.b9.com.br/) (Brazilian Portuguese, science). Download YouTube auto-captions or transcribe locally with Whisper. Useful for accessibility, language study, or text analysis.

## What's Included

- **Episode Metadata**: 500+ episodes with structured references, topics, and more (`data/episodes.json`)
- **Episode Index**: Human-readable catalog (`data/episode-index.md`)
- **Transcript Tools**: CLI to download YouTube captions or transcribe locally with Whisper

Transcript files are not included. You generate them locally using the `naruhodo` CLI.

## Quick Start

```bash
# Prerequisites: Python 3.10+, uv (https://docs.astral.sh/uv/)

git clone https://github.com/alastori/naruhodo-transcripts.git
cd naruhodo-transcripts
uv sync

# Fetch episode metadata, match YouTube links, download captions
uv run naruhodo refresh-index
uv run naruhodo discover-youtube
uv run naruhodo sync
```

The `sync` command shows a time estimate, asks for confirmation, handles YouTube rate limits automatically, and saves progress so you can Ctrl+C and resume.

## Local Whisper Transcription (Optional)

For episodes without YouTube links, or for higher-quality transcripts, transcribe directly from the podcast audio using [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon.

```bash
# Requires: Apple Silicon Mac, ffmpeg (brew install ffmpeg)
uv sync --extra whisper                          # transcription only
uv sync --extra diarize                          # transcription + speaker labels

uv run naruhodo whisper --no-diarize --yes       # plain transcripts
uv run naruhodo whisper --yes                    # with speaker labels (default)
uv run naruhodo whisper --llm claude:sonnet --yes  # use Claude for speaker ID
```

Speaker diarization labels each paragraph with the speaker name (Ken Fujioka vs Altay de Souza). It requires a [HuggingFace](https://huggingface.co/join) token and an LLM. See [Diarization Setup](docs/diarization-setup.md) for details.

> **Don't want diarization?** Use `--no-diarize`. No HuggingFace or LLM needed.

## Quality Checks

After transcription, verify quality:

```bash
uv run naruhodo quality-check                  # Whisper signals + episode metrics
uv run naruhodo quality-check --cross-validate # YouTube vs Whisper WER comparison
uv run naruhodo quality-check --llm-check 5    # LLM spot-check on flagged episodes
uv run naruhodo quality-check --json           # machine-readable output
```

## Commands

| Command | Description |
|---------|-------------|
| `naruhodo status` | Show current sync status |
| `naruhodo refresh-index` | Refresh episode metadata from RSS feed |
| `naruhodo discover-youtube` | Match YouTube playlist videos to RSS episodes |
| `naruhodo sync` | Download YouTube auto-captions |
| `naruhodo whisper` | Transcribe locally with MLX Whisper |
| `naruhodo quality-check` | Analyze transcript quality |

All commands support `--help` for full flag details. Use `-v` before the subcommand for verbose output.

## Data Schema

See [docs/schema.md](docs/schema.md) for the full `episodes.json` schema and structured reference format.

## Legal

See [DATA_LICENSE.md](DATA_LICENSE.md) for licensing, usage terms, and fair-use guidance.

- **Code**: MIT License ([LICENSE](LICENSE))
- **Metadata**: CC BY-NC 4.0 ([DATA_LICENSE.md](DATA_LICENSE.md))

## Attribution

This project is not affiliated with or endorsed by the Naruhodo podcast.

- **Naruhodo Podcast**: http://naruhodo.b9.com.br/
- **Hosts**: Ken Fujioka and Dr. Altay de Souza
- **Support the podcast**: https://orelo.cc/naruhodo or https://www.patreon.com/naruhodopodcast

## Contributing

```bash
uv sync --extra dev
uv run pytest         # run tests
uv run ruff check src # lint
```
