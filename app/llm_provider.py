"""
LLMProvider abstraction — swap AI backends without touching agent logic.
Ships with Ollama (free/local, default) and an OpenAI-compatible provider
(works with OpenAI, and most Anthropic/Google-compatible gateways that
speak the OpenAI chat-completions schema).
"""
from __future__ import annotations
import abc
import json
import httpx
from app.config import settings
from app.database import log_audit


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        ...


class OllamaProvider(LLMProvider):
    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        try:
            resp = httpx.post(
                f"{settings.LLM_BASE_URL}/api/chat",
                json={
                    "model": settings.LLM_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "format": "json" if json_mode else None,
                },
                timeout=90,
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except Exception as e:
            log_audit("llm_provider", "ERROR", f"Ollama call failed: {e}")
            return ""


class OpenAICompatibleProvider(LLMProvider):
    """Works with OpenAI and any gateway using the same /chat/completions schema.
    Also used for OpenRouter (https://openrouter.ai) — an aggregator that gives
    access to many free-tier models through one OpenAI-compatible API."""

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        if not settings.LLM_API_KEY:
            log_audit("llm_provider", "ERROR", "OpenAI-compatible provider selected but LLM_API_KEY missing")
            return ""
        base = settings.LLM_BASE_URL or "https://api.openai.com/v1"
        try:
            payload = {
                "model": settings.LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"}
            if "openrouter.ai" in base:
                # Optional but recommended by OpenRouter — improves routing/rate limits.
                # Not secrets, safe to hardcode.
                headers["HTTP-Referer"] = "https://github.com/"
                headers["X-Title"] = "VASU AI Project Hunter"
            resp = httpx.post(
                f"{base}/chat/completions",
                json=payload,
                headers=headers,
                timeout=90,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            log_audit("llm_provider", "ERROR", f"OpenAI-compatible call failed: {e}")
            return ""


_PROVIDERS = {
    "ollama": OllamaProvider,
    "openai_compatible": OpenAICompatibleProvider,
    "openrouter": OpenAICompatibleProvider,  # set LLM_BASE_URL=https://openrouter.ai/api/v1
    "anthropic": OpenAICompatibleProvider,   # point LLM_BASE_URL at an OpenAI-compatible Anthropic gateway
    "google": OpenAICompatibleProvider,      # point LLM_BASE_URL at an OpenAI-compatible Google gateway
}


def get_llm_provider() -> LLMProvider:
    cls = _PROVIDERS.get(settings.LLM_PROVIDER, OllamaProvider)
    return cls()


def safe_json_parse(text: str, default=None):
    """Strip markdown fences and parse JSON defensively — never raise into caller."""
    if not text:
        return default
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    try:
        return json.loads(cleaned.strip())
    except Exception:
        return default
