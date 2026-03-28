"""Pluggable LLM interface for speaker identification and quality checks.

Supports multiple backends via --llm flag:
    ollama:model_name       Local Ollama (default: qwen2.5:72b-instruct-q4_K_M)
    claude:model_alias      Claude CLI (uses your Claude subscription)
    codex:model_name        OpenAI Codex CLI (uses your ChatGPT subscription)
    openai:model_name       OpenAI API (requires OPENAI_API_KEY, pay-per-token)

Subscription-based (flat fee):
    claude:sonnet           Uses Claude Code CLI + your Claude subscription
    codex:o3                Uses Codex CLI + your ChatGPT Plus/Pro subscription

API-based (pay-per-token):
    openai:gpt-4o           Uses OpenAI API + OPENAI_API_KEY

Local (free):
    ollama:qwen2.5:72b      Uses local Ollama server

Usage:
    from src.llm import llm_call, load_prompt

    prompt = load_prompt("speaker_id_regular", transcript=text)
    result = llm_call("ollama:qwen2.5:72b", prompt)
    result = llm_call("claude:sonnet", prompt)
    result = llm_call("codex:o3", prompt)
"""

import json
import logging
import subprocess
from pathlib import Path

from .config import DEFAULT_LLM

logger = logging.getLogger("naruhodo")

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Ollama config
OLLAMA_URL = "http://localhost:11434/api/generate"


def load_prompt(name: str, **kwargs) -> str:
    """Load a prompt template from the prompts/ directory and fill in variables.

    Uses format_map with a defaultdict to safely handle stray braces that
    may appear in user-supplied values (e.g., guest names containing '{' or '}').
    """
    from collections import defaultdict

    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    template = path.read_text(encoding="utf-8")
    return template.format_map(defaultdict(str, **kwargs))


def parse_llm_spec(spec: str) -> tuple:
    """Parse an LLM spec string into (provider, model).

    Examples:
        "ollama:qwen2.5:72b"     -> ("ollama", "qwen2.5:72b")
        "claude:sonnet"          -> ("claude", "sonnet")
        "codex:o3"               -> ("codex", "o3")
        "openai:gpt-4o"          -> ("openai", "gpt-4o")
        "qwen2.5:72b"           -> ("ollama", "qwen2.5:72b")
    """
    for prefix in ("claude:", "ollama:", "codex:", "openai:"):
        if spec.startswith(prefix):
            return prefix[:-1], spec[len(prefix):]
    # Default to ollama for bare model names
    return "ollama", spec


def llm_call(
    llm_spec: str,
    prompt: str,
    timeout: int = 300,
) -> dict:
    """Call an LLM and parse JSON response.

    Args:
        llm_spec: Provider:model string
        prompt: The full prompt to send
        timeout: Timeout in seconds

    Returns:
        Parsed JSON dict from the LLM response
    """
    provider, model = parse_llm_spec(llm_spec)

    if provider == "ollama":
        raw = _call_ollama(model, prompt, timeout)
    elif provider == "claude":
        raw = _call_claude(model, prompt, timeout)
    elif provider == "codex":
        raw = _call_codex(model, prompt, timeout)
    elif provider == "openai":
        raw = _call_openai(model, prompt, timeout)
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
    """Call Claude CLI (uses your Claude subscription)."""
    cmd = [
        "claude",
        "-p",
        "--model", model,
        "--output-format", "text",
        "--no-session-persistence",
        prompt,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            raise RuntimeError(f"Claude CLI error: {result.stderr[:200]}")
        return result.stdout
    except FileNotFoundError:
        raise RuntimeError(
            "Claude CLI not found. Install from https://claude.ai/download"
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s") from None


def _call_codex(model: str, prompt: str, timeout: int) -> str:
    """Call OpenAI Codex CLI (uses your ChatGPT subscription via OAuth).

    Note: ChatGPT subscription only supports Codex-specific models.
    The default model from ~/.codex/config.toml is used if model is "default".
    """
    cmd = ["codex", "exec", "--json"]
    if model and model != "default":
        cmd.extend(["--model", model])
    cmd.append(prompt)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        # Codex --json outputs NDJSON (one JSON object per line)
        # Find the agent_message item with the response text
        for line in result.stdout.strip().split("\n"):
            try:
                event = json.loads(line)
                if event.get("type") == "item.completed":
                    item = event.get("item", {})
                    if item.get("type") == "agent_message":
                        return item.get("text", "")
                if event.get("type") == "error":
                    raise RuntimeError(f"Codex error: {event.get('message', '')[:200]}")
            except json.JSONDecodeError:
                continue
        # If no agent_message found, check for errors
        if result.returncode != 0:
            raise RuntimeError(f"Codex CLI error: {result.stderr[:200]}")
        return result.stdout
    except FileNotFoundError:
        raise RuntimeError(
            "Codex CLI not found. Install: npm install -g @openai/codex\n"
            "Then authenticate: codex login"
        ) from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Codex CLI timed out after {timeout}s") from None


def _call_openai(model: str, prompt: str, timeout: int) -> str:
    """Call OpenAI API (requires OPENAI_API_KEY, pay-per-token)."""
    import os
    import requests

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not set. Get one at https://platform.openai.com/api-keys\n"
            "For subscription-based access, use codex: instead (e.g., --llm codex:o3)"
        )

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except KeyError:
        raise RuntimeError("Unexpected OpenAI response format") from None
    except Exception as e:
        raise RuntimeError(f"OpenAI API call failed ({model}): {e}") from e


def _parse_json_response(raw: str) -> dict:
    """Extract and parse JSON from an LLM response."""
    raw = raw.strip()
    # Handle markdown code blocks
    if "```" in raw:
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
