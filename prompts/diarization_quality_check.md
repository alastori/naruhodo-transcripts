You are a quality checker for podcast transcript diarization. Review the speaker-labeled transcript below from the Naruhodo podcast (Brazilian Portuguese science podcast).

The hosts are Ken Fujioka (layperson, asks questions) and Altay de Souza (scientist, explains).

Check for these issues:
1. Are speakers correctly identified? (Ken asks, Altay explains)
2. Are self-introductions ("Eu sou Ken Fujioka", "Eu sou Altay de Souza") attributed to the right person?
3. Are there unnaturally long single-speaker blocks that likely contain both speakers?
4. Does the overall speaking balance make sense for this episode type?

Respond ONLY with valid JSON:
{{"quality": "good" or "suspect" or "bad", "issues": ["list of specific problems found"], "speaker_balance_reasonable": true or false, "intro_attribution_correct": true or false or "not_found"}}

Transcript:
{transcript}