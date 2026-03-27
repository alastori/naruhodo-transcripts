# Diarization Setup

Speaker diarization labels each transcript paragraph with the speaker name. It uses [pyannote](https://github.com/pyannote/pyannote-audio) community-1 for speaker detection and a pluggable LLM for speaker identification.

## Prerequisites

- Apple Silicon Mac (M1/M2/M3/M4)
- ffmpeg (`brew install ffmpeg`)

## Install

```bash
uv sync --extra diarize
```

## HuggingFace Setup (one-time)

1. Create a free account at https://huggingface.co/join
2. Accept the model terms (click "Agree" on each page):
   - https://huggingface.co/pyannote/speaker-diarization-community-1
   - https://huggingface.co/pyannote/segmentation-3.0
3. Create an access token at https://huggingface.co/settings/tokens (Read permission)
4. Set the token:
   ```bash
   export HF_TOKEN="hf_your_token_here"
   ```

## LLM Setup

The speaker identification step uses an LLM to determine which anonymous speaker label (SPEAKER_00, SPEAKER_01) corresponds to Ken Fujioka vs Altay de Souza. This is pluggable via `--llm`:

```bash
# Option A: Ollama (local, free, default)
ollama pull qwen2.5:72b-instruct-q4_K_M
# Ollama must be running: launch the app or run `ollama serve`
naruhodo whisper --llm ollama:qwen2.5:72b-instruct-q4_K_M

# Option B: Claude CLI
naruhodo whisper --llm claude:sonnet

# Option C: Claude Opus (highest quality, for verification)
naruhodo whisper --llm claude:opus
```

The default is Ollama. Prompt templates are in `prompts/` and can be edited without changing code.

## Usage

```bash
# With diarization (default when diarize extra is installed)
uv run naruhodo whisper --yes

# Specific episode
uv run naruhodo whisper --episode 400 --yes

# Skip diarization
uv run naruhodo whisper --no-diarize --yes
```

## How It Works

1. **pyannote community-1** detects speaker segments (who speaks when) using VBx clustering with PLDA on Apple Silicon GPU (MPS)
2. **Whisper word timestamps** align transcript text to speaker segments
3. **LLM** identifies which anonymous speaker is Ken vs Altay based on conversational patterns, self-introductions, and content

For interview episodes, the LLM receives the guest name from episode metadata to identify three participants (Ken + guest; Altay is not present in interviews).
