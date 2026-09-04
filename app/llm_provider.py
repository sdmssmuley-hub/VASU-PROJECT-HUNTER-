"""
LLMProvider abstraction — swap AI backends without touching agent logic.
Ships with Ollama (free/local, default) and an OpenAI-compatible provider
(works with OpenAI, and most Anthropic/Google-compatible gateways that
speak the OpenAI chat-completions schema).

FIX (see audit_logs investigation): previously, a successful-but-unparseable
LLM response was silently swallowed — no exception, so nothing was logged,
and safe_json_parse's default=[] made it look identical to "the LLM found
nothing." That's why every run showed "0 raw candidates" with zero
llm_provider log entries even though search was returning 30-40+ results.

Changes:
  1. Every completion call now logs a preview of what actually came back
     (component="llm_provider", level=INFO on success, WARNING on empty/odd
     responses, ERROR on exceptions) — so audit_logs will show the real
     reason instead of silence.
  2. If json_mode is requested and the provider rejects `response_format`
     (many free/open models on OpenRouter don't support it and return a 4xx),
     we now retry once WITHOUT response_format instead of just failing.
  3. safe_json_parse is more forgiving: if the whole string isn't valid JSON
     (e.g. the model added a sentence before/after the array), it now tries
     to pull out the first [...] or {...} block and parse just that.
"""
from __future__ import annotations
import abc
import json
import re
import httpx
from app.config import settings
from app.database import log_audit


class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        ...


def _preview(text: str, n: int = 300) -> str:
    if not text:
        return "<empty>"
    text = text.strip().replace("\n", " ")
    return text[:n] + ("..." if len(text) > n else "")


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
            content = resp.json().get("message", {}).get("content", "")
            if content:
                log_audit("llm_provider", "INFO", f"Ollama response ({len(content)} chars): {_preview(content)}")
            else:
                log_audit("llm_provider", "WARNING", "Ollama returned an empty message content.")
            return content
        except Exception as e:
            log_audit("llm_provider", "ERROR", f"Ollama call failed: {e}")
            return ""


class OpenAICompatibleProvider(LLMProvider):
    """Works with OpenAI and any gateway using the same /chat/completions schema.
    Also used for OpenRouter (https://openrouter.ai) — an aggregator that gives
    access to many free-tier models through one OpenAI-compatible API."""

    def _call(self, base: str, headers: dict, payload: dict) -> httpx.Response:
        return httpx.post(f"{base}/chat/completions", json=payload, headers=headers, timeout=90)

    def complete(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        if not settings.LLM_API_KEY:
            log_audit("llm_provider", "ERROR", "OpenAI-compatible provider selected but LLM_API_KEY missing")
            return ""

        base = settings.LLM_BASE_URL or "https://api.openai.com/v1"
        headers = {"Authorization": f"Bearer {settings.LLM_API_KEY}"}
        if "openrouter.ai" in base:
            headers["HTTP-Referer"] = "https://github.com/"
            headers["X-Title"] = "VASU AI Project Hunter"

        payload = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            resp = self._call(base, headers, payload)

            # Some free/open models on OpenRouter reject response_format with a 4xx.
            # Retry once without it instead of failing the whole query.
            if json_mode and resp.status_code >= 400:
                log_audit(
                    "llm_provider", "WARNING",
                    f"Model rejected response_format (HTTP {resp.status_code}), retrying without it.",
                )
                payload.pop("response_format", None)
                resp = self._call(base, headers, payload)

            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            if content:
                log_audit("llm_provider", "INFO", f"LLM response ({len(content)} chars): {_preview(content)}")
            else:
                finish_reason = data["choices"][0].get("finish_reason", "unknown")
                log_audit(
                    "llm_provider", "WARNING",
                    f"LLM returned empty content (finish_reason={finish_reason}). "
                    f"Model may not support this request type or hit a content filter.",
                )
            return content or ""
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


def _extract_json_block(text: str):
    """Last-resort recovery: pull the first [...] or {...} block out of text
    that otherwise isn't valid JSON on its own (e.g. model added a sentence
    before/after it) and try to parse just that."""
    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = text.find(open_ch)
        end = text.rfind(close_ch)
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]
            try:
                return json.loads(candidate)
            except Exception:
                continue
    return None


def safe_json_parse(text: str, default=None):
    """Strip markdown fences and parse JSON defensively — never raise into caller.
    Logs *why* parsing failed instead of silently returning `default`, so a bad
    LLM response is distinguishable from "the LLM genuinely found nothing"."""
    if not text:
        return default

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except Exception as e:
        recovered = _extract_json_block(cleaned)
        if recovered is not None:
            log_audit("llm_provider", "WARNING", f"JSON parse needed fallback extraction (initial error: {e})")
            return recovered
        log_audit("llm_provider", "ERROR", f"JSON parse failed, no recoverable block found: {e}. Text: {_preview(text)}")
        return default
