"""Pluggable LLM interface for speaker identification and quality checks.

Supports multiple backends:
    ollama:model_name       Local Ollama (default)
    claude:model_alias      Claude CLI (sonnet, opus, haiku)

Usage:
    from src.llm import llm_call, load_prompt

    prompt = load_prompt("speaker_id_regular", transcript=text)
    result = llm_call("ollama:qwen2.5:72b", prompt)
    result = llm_call("claude:sonnet", prompt)
"""

import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("naruhodo")

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Default LLM for each use case (can be overridden via --llm flag)
DEFAULT_LLM = "ollama:qwen2.5:72b-instruct-q4_K_M"

# Ollama config
OLLAMA_URL = "http://localhost:11434/api/generate"


def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt template from the prompts/ directory and fill in variables.

    Args:
        name: Prompt filename without extension (e.g., "speaker_id_regular")
        **kwargs: Variables to substitute in the template

    Returns:
        Formatted prompt string
    """
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    template = path.read_text(encoding="utf-8")
    return template.format(**kwargs)


def parse_llm_spec(spec: str) -> tuple[str, str]:
    """Parse an LLM spec string into (provider, model).

    Examples:
        "ollama:qwen2.5:72b"     -> ("ollama", "qwen2.5:72b")
        "claude:sonnet"          -> ("claude", "sonnet")
        "claude:opus"            -> ("claude", "opus")
        "qwen2.5:72b"           -> ("ollama", "qwen2.5:72b")  # default provider
    """
    if spec.startswith("claude:"):
        return "claude", spec[7:]
    if spec.startswith("ollama:"):
        return "ollama", spec[7:]
    # Default to ollama for bare model names
    return "ollama", spec


def llm_call(
    llm_spec: str,
    prompt: str,
    timeout: int = 300,
) -> dict:
    """Call an LLM and parse JSON response.

    Args:
        llm_spec: Provider:model string (e.g., "ollama:qwen2.5:72b", "claude:sonnet")
        prompt: The full prompt to send
        timeout: Timeout in seconds

    Returns:
        Parsed JSON dict from the LLM response

    Raises:
        RuntimeError: If the LLM call fails or returns invalid JSON
    """
    provider, model = parse_llm_spec(llm_spec)

    if provider == "ollama":
        raw = _call_ollama(model, prompt, timeout)
    elif provider == "claude":
        raw = _call_claude(model, prompt, timeout)
    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

    return _parse_json_response(raw)


def _call_ollama(model: str, prompt: str, timeout: int) -> str:
    """Call Ollama API and return raw response text."""
    import requests

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("response", "")
    except Exception as e:
        raise RuntimeError(f"Ollama call failed ({model}): {e}") from e


def _call_claude(model: str, prompt: str, timeout: int) -> str:
    """Call Claude CLI and return raw response text."""
    cmd = [
        "claude",
        "-p",
        "--model", model,
        "--output-format", "text",
        "--no-session-persistence",
        "--bare",
        prompt,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr[:200]}")
        return result.stdout
    except FileNotFoundError:
        raise RuntimeError(
            "Claude CLI not found. Install from https://claude.ai/claude-code"
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s") from None


def _parse_json_response(raw: str) -> dict:
    """Extract and parse JSON from an LLM response."""
    raw = raw.strip()
    # Handle markdown code blocks
    if "```" in raw:
        # Extract content between first ``` pair
        parts = raw.split("```")
        if len(parts) >= 3:
            raw = parts[1]
            if raw.startswith("json"):
                raw = raw[4:]
    raw = raw.strip().strip("`").strip()
    if raw.startswith("json"):
        raw = raw[4:].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM returned invalid JSON: {raw[:200]}") from e
