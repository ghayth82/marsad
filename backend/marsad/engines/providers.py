"""المزوّدون: طبقة واحدة لكل المحركات. لا أدوات ولا صلاحيات تنفيذ للمحركات: نص يدخل ونص يخرج.

- anthropic:          Claude (Haiku، Sonnet، Opus)
- openai:             OpenAI
- gemini:             Google Gemini
- openai_compatible:  أي مزوّد متوافق مع واجهة OpenAI، وvLLM
- ollama:             محرك محلي عبر Ollama (واجهته المتوافقة مع OpenAI)
- fake:               محرك وهمي ثابت المخرجات للاختبارات (لا يتصل بشيء)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass

import httpx

PROVIDERS = {
    "anthropic": {"label": "Claude (Anthropic)", "local": False, "base_url": "https://api.anthropic.com"},
    "openai": {"label": "OpenAI", "local": False, "base_url": "https://api.openai.com/v1"},
    "gemini": {"label": "Google Gemini", "local": False, "base_url": "https://generativelanguage.googleapis.com/v1beta"},
    "openai_compatible": {"label": "مزوّد متوافق مع OpenAI", "local": False, "base_url": ""},
    "ollama": {"label": "محلي عبر Ollama", "local": True, "base_url": "http://127.0.0.1:11434/v1"},
    "fake": {"label": "وهمي (للاختبار)", "local": True, "base_url": ""},
}

TIMEOUT = httpx.Timeout(180.0, connect=15.0)


class ProviderError(Exception):
    pass


@dataclass
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    model_version: str


def _post(url: str, headers: dict, body: dict) -> dict:
    try:
        r = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise ProviderError(f"تعذّر الاتصال بالمحرك: {e.__class__.__name__}") from None
    if r.status_code >= 400:
        try:
            detail = r.json()
            msg = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else detail.get("error")
        except ValueError:
            msg = None
        hint = {401: "المفتاح غير صحيح", 403: "المفتاح لا يملك صلاحية", 404: "اسم النموذج أو العنوان غير صحيح",
                429: "تجاوزت حدود المزوّد مؤقتًا"}.get(r.status_code, "خطأ من المزوّد")
        raise ProviderError(f"{hint} ({r.status_code}){': ' + str(msg)[:300] if msg else ''}")
    return r.json()


def complete(provider: str, *, model: str, system: str, user: str, api_key: str | None,
             base_url: str = "", max_tokens: int = 2000, options: dict | None = None) -> Completion:
    options = options or {}
    base = (base_url or PROVIDERS.get(provider, {}).get("base_url", "")).rstrip("/")

    if provider == "fake":
        return _fake(options, user)

    if provider == "anthropic":
        if not api_key:
            raise ProviderError("لا يوجد مفتاح لهذا المحرك")
        d = _post(f"{base}/v1/messages",
                  {"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                  {"model": model, "max_tokens": max_tokens, "system": system,
                   "messages": [{"role": "user", "content": user}]})
        text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        u = d.get("usage", {})
        return Completion(text, u.get("input_tokens", 0), u.get("output_tokens", 0), d.get("model", model))

    if provider == "gemini":
        if not api_key:
            raise ProviderError("لا يوجد مفتاح لهذا المحرك")
        d = _post(f"{base}/models/{model}:generateContent",
                  {"x-goog-api-key": api_key, "content-type": "application/json"},
                  {"systemInstruction": {"parts": [{"text": system}]},
                   "contents": [{"role": "user", "parts": [{"text": user}]}],
                   "generationConfig": {"maxOutputTokens": max_tokens, "responseMimeType": "application/json"}})
        cands = d.get("candidates") or []
        if not cands:
            raise ProviderError("لم يُرجع المحرك أي مخرج (قد يكون حجبه لسبب يخص المحتوى)")
        text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
        u = d.get("usageMetadata", {})
        return Completion(text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0), d.get("modelVersion", model))

    if provider in ("openai", "openai_compatible", "ollama"):
        if provider != "ollama" and not api_key:
            raise ProviderError("لا يوجد مفتاح لهذا المحرك")
        if not base:
            raise ProviderError("أدخل عنوان المزوّد")
        body = {"model": model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        body["max_completion_tokens" if provider == "openai" else "max_tokens"] = max_tokens
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        d = _post(f"{base}/chat/completions", headers, body)
        choices = d.get("choices") or []
        if not choices:
            raise ProviderError("لم يُرجع المحرك أي مخرج")
        u = d.get("usage") or {}
        return Completion(choices[0].get("message", {}).get("content") or "", u.get("prompt_tokens", 0),
                          u.get("completion_tokens", 0), d.get("model", model))

    raise ProviderError(f"مزوّد غير معروف: {provider}")


def _fake(options: dict, user: str) -> Completion:
    """مخرجات ثابتة من إعدادات المحرك: fake_output (نص أو JSON)، fake_fail، fake_delay، fake_tokens."""
    if options.get("fake_delay"):
        time.sleep(float(options["fake_delay"]))
    if options.get("fake_fail"):
        raise ProviderError(str(options.get("fake_fail")) if isinstance(options.get("fake_fail"), str) else "تعطّل المحرك الوهمي")
    out = options.get("fake_output", {"summary": "مخرج وهمي", "points": []})
    text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    tin, tout = options.get("fake_tokens", [max(1, len(user) // 3), max(1, len(text) // 3)])
    return Completion(text, int(tin), int(tout), "fake-1")
