"""Provider-independent LLM interface with JSON-schema structured output.

Configured only through environment variables; never logs prompts or keys.
  LLM_PROVIDER=none|openai|ollama
  OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL (any OpenAI-compatible endpoint)
  OLLAMA_BASE_URL, OLLAMA_MODEL
"""
from __future__ import annotations

import json
import time
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class LLMUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMResponse:
    data: dict
    provider: str
    model: str


class LLMProvider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: dict, schema_name: str) -> LLMResponse: ...


def _post(url: str, payload: dict, headers: dict, timeout: int, retries: int = 4) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "clinical-ai-platform/0.1", **headers})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < retries:  # rate limit: honour Retry-After, else back off
                wait = exc.headers.get("retry-after") if exc.headers else None
                time.sleep(min(60.0, float(wait)) if wait and wait.replace(".", "", 1).isdigit() else 2 ** (attempt + 1))
                continue
            raise LLMUnavailable(f"LLM request failed: HTTPError: {exc.code}") from exc
        except OSError as exc:  # URLError/timeouts; message never contains the key
            raise LLMUnavailable(f"LLM request failed: {type(exc).__name__}") from exc
    raise LLMUnavailable("LLM request failed: retries exhausted")


class OpenAICompatibleProvider:
    name = "openai-compatible"

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1", timeout: int = 60):
        self._key, self.model, self.base_url, self.timeout = api_key, model, base_url.rstrip("/"), timeout

    def complete_json(self, system, user, schema, schema_name):
        out = _post(f"{self.base_url}/chat/completions", {
            "model": self.model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": False}},
        }, {"Authorization": f"Bearer {self._key}"}, self.timeout)
        content = out["choices"][0]["message"]["content"]
        return LLMResponse(json.loads(content), self.name, out.get("model", self.model))


class OllamaProvider:
    name = "ollama"

    def __init__(self, model: str, base_url: str = "http://localhost:11434", timeout: int = 120):
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout

    def complete_json(self, system, user, schema, schema_name):
        out = _post(f"{self.base_url}/api/chat", {
            "model": self.model, "stream": False, "format": schema, "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, {}, self.timeout)
        return LLMResponse(json.loads(out["message"]["content"]), self.name, out.get("model", self.model))


def provider_from_env() -> LLMProvider:
    kind = os.environ.get("LLM_PROVIDER", "none").strip().lower()
    if kind == "openai":
        key, model = os.environ.get("OPENAI_API_KEY"), os.environ.get("OPENAI_MODEL")
        if not key or not model:
            raise LLMUnavailable("LLM_PROVIDER=openai requires OPENAI_API_KEY and OPENAI_MODEL")
        return OpenAICompatibleProvider(key, model, os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    if kind == "ollama":
        model = os.environ.get("OLLAMA_MODEL")
        if not model:
            raise LLMUnavailable("LLM_PROVIDER=ollama requires OLLAMA_MODEL")
        return OllamaProvider(model, os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))
    raise LLMUnavailable("No LLM provider configured (LLM_PROVIDER=none)")
