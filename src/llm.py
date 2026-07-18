"""LLM access layer. Primary: Google Gemini free tier. Fallback: Pollinations (no key)."""
import json
import os
import re
import time

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _gemini(prompt: str, model: str, api_key: str) -> str:
    resp = requests.post(
        GEMINI_URL.format(model=model),
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.9, "maxOutputTokens": 8192},
        },
        timeout=90,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _pollinations(prompt: str) -> str:
    import random
    resp = requests.post(
        "https://text.pollinations.ai/openai",
        json={
            "messages": [
                {"role": "system", "content": "Reasoning: low"},
                {"role": "user", "content": prompt},
            ],
            "model": "openai-fast",
            "seed": random.randint(1, 10**9),
            "max_tokens": 6000,
        },
        timeout=180,
    )
    resp.raise_for_status()
    resp.encoding = "utf-8"
    data = resp.json()
    content = data["choices"][0]["message"].get("content") or ""
    if not content.strip():
        # anonymous tier often burns its whole budget on reasoning and returns nothing
        raise RuntimeError("pollinations returned empty content (token budget exhausted)")
    return content


FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest"]


def quality_model(config: dict) -> str:
    """The model for the few calls a day where the writing IS the product
    (topic research, script, critic). Falls back through the normal chain if
    its free-tier quota is exhausted, so it can never block a run."""
    return config.get("llm", {}).get("quality_model", "gemini-2.5-pro")


def generate(prompt: str, config: dict, model: str | None = None) -> str:
    """Return raw LLM text for a prompt, retrying and falling back as needed.

    model: optional override tried before the configured primary."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    primary = config.get("llm", {}).get("model", "gemini-flash-latest")
    wanted = [m for m in (model, primary) if m]
    models = list(dict.fromkeys(wanted + FALLBACK_MODELS))
    errors = []
    if api_key:
        for model in models:
            for attempt in range(2):
                try:
                    return _gemini(prompt, model, api_key)
                except Exception as e:  # rate limits, transient 5xx
                    errors.append(f"{model} attempt {attempt + 1}: {e}")
                    time.sleep(10 * (attempt + 1))
    for attempt in range(2):
        try:
            return _pollinations(prompt)
        except Exception as e:
            errors.append(f"pollinations attempt {attempt + 1}: {e}")
            time.sleep(5)
    raise RuntimeError("All LLM providers failed:\n" + "\n".join(errors))


def generate_json(prompt: str, config: dict, model: str | None = None) -> dict:
    """Ask for JSON and parse it robustly (strips markdown fences, finds outer braces)."""
    last_err = None
    for _ in range(3):
        text = generate(prompt, config, model=model)
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError as e:
                last_err = e
        else:
            last_err = f"no JSON object in response (got {len(text)} chars: {text[:200]!r})"
    raise RuntimeError(f"LLM did not return valid JSON: {last_err}")
