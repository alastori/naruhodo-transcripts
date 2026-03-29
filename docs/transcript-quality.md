# Transcript Quality Notes

## Source comparison

| Source | Text quality | Proper nouns | Speaker labels | Speed |
|--------|-------------|-------------|----------------|-------|
| **YouTube VTT (Web Video Text Tracks)** | Low. Repeated phrases, `[Música]` tags, garbled text | "Naru Rodolfo", "fiquei Fujioca" | Via diarization only | ~3s/episode |
| **Whisper large-v3** | High. Clean Portuguese, correct sentences | "Naruhodo", "Ken Fujioka" (with vocabulary hinting) | Via diarization | ~6 min/episode |

YouTube auto-captions are fast and free but the text is noisy. Whisper with vocabulary hinting (`--initial-prompt`) produces significantly better text. For analysis requiring accurate text, run `naruhodo transcribe --source whisper` to upgrade VTT episodes.

## Diarization

Speaker detection uses pyannote community-1 (VBx clustering, MPS). Speaker identification uses an LLM (Ollama with qwen2.5:72b by default, configurable via `--llm`).

Typical results on this podcast:
- **Speaker balance**: Ken 15-27% / Altay 72-84% (Altay explains, Ken asks)
- **Turn count**: 50-100+ per episode
- **Intro attribution**: "Eu sou Ken Fujioka" correctly assigned in spot checks

pyannote 3.1 failed on this podcast (95/5 splits). Community-1 (pyannote 4.0) resolved this with VBx clustering.

## Quality grades

Each episode gets a grade stored in `transcript_quality.grade` in episodes.json:

| Grade | Criteria | Action |
|-------|----------|--------|
| **A** | Whisper transcript, confidence >= 0.90, no critical flags | None needed |
| **B** | Whisper with minor issues, or YouTube VTT with speaker labels | Upgrade to Whisper when time permits |
| **C** | YouTube VTT without labels, low confidence, or critical flags | Re-transcribe with `naruhodo transcribe --source whisper` |

The `naruhodo status` dashboard shows the grade distribution and suggests the next action.

## Quality flags

The pipeline flags episodes automatically:
- `low_confidence`: mean logprob below -0.8
- `repeated_ngrams`: more than 5 repeated 6-grams (often legitimate: sponsor reads, intros)
- `few_speaker_turns`: fewer than 10 turns for a 20+ min episode

Review flagged episodes with `naruhodo status`.
