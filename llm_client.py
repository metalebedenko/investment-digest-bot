"""
Лёгкий клиент для LLM-провайдеров:
- Ollama
- OpenAI
- OpenAI-compatible endpoints
"""

from __future__ import annotations

import logging

import requests


logger = logging.getLogger(__name__)


def _normalize_base_url(provider: str, base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        if provider == "ollama":
            return "http://localhost:11434"
        return "https://api.openai.com/v1"
    return base


def chat_completion(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.7,
    timeout_sec: int = 180,
) -> str:
    """Возвращает текст первого ответа модели."""
    if provider == "ollama":
        return _ollama_chat(
            model=model,
            base_url=base_url,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            timeout_sec=timeout_sec,
        )

    if provider in {"openai", "openai_compatible"}:
        return _openai_like_chat(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            timeout_sec=timeout_sec,
        )

    raise ValueError(f"Неподдерживаемый provider: {provider}")


def _ollama_chat(
    *,
    model: str,
    base_url: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout_sec: int,
) -> str:
    base = _normalize_base_url("ollama", base_url)
    response = requests.post(
        f"{base}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 10240,
            },
        },
        timeout=timeout_sec,
    )
    response.raise_for_status()
    content = response.json().get("message", {}).get("content", "")
    if not content:
        raise ValueError("Ollama вернул пустой ответ")
    return content


def _openai_like_chat(
    *,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    timeout_sec: int,
) -> str:
    if not api_key:
        raise ValueError("API key не задан")

    base = _normalize_base_url("openai_compatible", base_url)
    endpoint = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        },
        timeout=timeout_sec,
    )
    response.raise_for_status()

    payload = response.json()
    choices = payload.get("choices", [])
    if not choices:
        raise ValueError("LLM API вернул ответ без choices")

    message = choices[0].get("message", {})
    content = message.get("content", "")

    if isinstance(content, list):
        text_chunks = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_chunks.append(item.get("text", ""))
        content = "".join(text_chunks)

    if not content:
        raise ValueError("LLM API вернул пустой content")
    return content
