# Data License

This document explains the licensing and rights for the different types of data in this repository.

## Code (MIT License)

All Python code in `src/`, prompt templates in `prompts/`, and documentation in `docs/` are released under the MIT License. See [LICENSE](LICENSE) for details.

## Episode Metadata (CC BY-NC 4.0)

The episode metadata in `data/episodes.json` and `data/episode-index.md` is derived from the Naruhodo podcast's public RSS feed. This metadata was extracted from the podcast's publicly available RSS feed for research purposes.

This metadata is provided under [Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)](https://creativecommons.org/licenses/by-nc/4.0/).

**You are free to:**
- Share: copy and redistribute the material in any medium or format
- Adapt: remix, transform, and build upon the material

**Under the following terms:**
- Attribution: you must give appropriate credit to the Naruhodo podcast
- NonCommercial: you may not use the material for commercial purposes

### What's in the metadata

The metadata includes: episode titles, dates, durations, topics, episode types, guest names, summaries, classified academic references (with DOIs), audio URLs, and cover art URLs. All of this is derived from the publicly available RSS feed.

**Note:** The `audio_url` field is provided for reference and single-episode playback only. Please do not use it for bulk downloading or redistribution of audio files.

The `raw_description` field preserves the original HTML from the RSS feed for researchers who need the full show notes with formatting.

## Transcripts (Not Distributed)

Transcript files (`.vtt`, `.whisper.md`) and quality sidecars (`.quality.json`) are **not included** in this repository. Users generate their own copies using the provided tools.

### Why Not Include Transcripts?

1. **Copyright**: The spoken words in the podcast are copyrighted by the Naruhodo creators
2. **YouTube ToS**: Redistribution of YouTube captions may violate terms of service
3. **Whisper transcripts**: Generated from copyrighted audio, same copyright considerations apply
4. **Best practice**: Similar projects provide tools, not derived content

### Personal Use Disclaimer

Transcripts generated using these tools should be used for:
- Personal research and study
- Accessibility purposes
- Educational use
- Non-commercial text analysis

**Do not redistribute generated transcripts.**

## Attribution

If you use this project or its metadata, please credit:

- **Naruhodo Podcast**: http://naruhodo.b9.com.br/
- **Hosts**: Ken Fujioka and Dr. Altay de Souza
- **Support the podcast**: https://orelo.cc/naruhodo or https://www.patreon.com/naruhodopodcast

## Takedown

If you are the rights holder of the Naruhodo podcast and would like any data removed from this repository, please open an issue or email the repository maintainer. We will respond promptly and remove the requested content.

## Questions?

If you have questions about licensing or usage, please open an issue on GitHub.
