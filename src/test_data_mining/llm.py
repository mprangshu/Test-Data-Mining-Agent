"""
llm.py — Google Gemini LLM seam.

The deterministic nodes (`generate`, `synthesise`) call ``get_llm()`` to obtain a text-generation
callable. It returns ``None`` when no key is configured, so callers transparently fall back to
the offline deterministic path (and all tests run without network or a key).

Configuration (never committed — set in your shell or a gitignored ``.env``):
  * ``GEMINI_API_KEY``  — required to enable the LLM (provided by the user).
  * ``GEMINI_MODEL``    — optional, defaults to ``gemini-2.5-flash``.

Uses the ``google-genai`` SDK (``from google import genai``). Anti-hallucination still applies:
callers validate every LLM-produced value against field constraints before using it.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

_DEFAULT_MODEL = "gemini-2.5-flash"


def _load_dotenv() -> None:
    """Populate os.environ from a gitignored repo-root .env (real env vars take precedence)."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    path = os.path.join(root, ".env")
    if not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except OSError:
        pass


_load_dotenv()


def get_llm() -> Optional[Callable[[str], str]]:
    """Return a ``prompt -> text`` callable backed by Gemini, or ``None`` if unavailable."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai
    except Exception:
        return None

    # Corporate-proxy TLS: verify against a CA bundle if one is configured. Honours
    # GEMINI_CA_BUNDLE, then SSL_CERT_FILE / REQUESTS_CA_BUNDLE. Passed to the underlying
    # httpx client via HttpOptions.client_args (no insecure verify=False shortcut).
    ca = (os.environ.get("GEMINI_CA_BUNDLE")
          or os.environ.get("SSL_CERT_FILE")
          or os.environ.get("REQUESTS_CA_BUNDLE"))
    if ca and os.path.exists(ca):
        from google.genai import types
        http_options = types.HttpOptions(client_args={"verify": ca}, async_client_args={"verify": ca})
        client = genai.Client(api_key=api_key, http_options=http_options)
    else:
        client = genai.Client(api_key=api_key)
    model = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)

    def _call(prompt: str) -> str:
        resp = client.models.generate_content(model=model, contents=prompt)
        return (getattr(resp, "text", "") or "").strip()

    return _call
