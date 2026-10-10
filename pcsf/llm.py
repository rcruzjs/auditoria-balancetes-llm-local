"""Cliente mínimo para LLMs locais com API compatível com OpenAI (llama-swap do chat-local ou Ollama).

Configuração no .env:
    LLM_URL=http://127.0.0.1:8080      (chat-local / llama-swap)  ou  http://127.0.0.1:11434 (Ollama)
    LLM_MODEL=chat-8b                   ou  qwen2.5:7b
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

from . import db  # noqa: F401  (carrega o .env)


def config() -> tuple[str, str]:
    return os.environ.get("LLM_URL", "http://127.0.0.1:8080"), os.environ.get("LLM_MODEL", "chat-8b")


def chat_json(system: str, user: str, url: str | None = None, modelo: str | None = None,
              temperatura: float = 0.0, timeout: int = 600) -> tuple[dict, float]:
    """Envia a conversa e devolve (JSON da resposta, segundos)."""
    u, m = config()
    url, modelo = url or u, modelo or m
    corpo = {
        "model": modelo,
        "temperature": temperatura,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},   # Qwen3: sem raciocínio longo
    }
    req = urllib.request.Request(f"{url.rstrip('/')}/v1/chat/completions", data=json.dumps(corpo).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read())
    texto = resp["choices"][0]["message"]["content"] or ""
    texto = re.sub(r"<think>.*?</think>", "", texto, flags=re.S).strip()
    m_json = re.search(r"\{.*\}", texto, flags=re.S)
    return json.loads(m_json.group(0) if m_json else texto), time.perf_counter() - t0
