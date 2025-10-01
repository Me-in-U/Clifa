import os
from typing import Optional

# OpenAI SDK v1.x
try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


def translate_to_english(text: str, api_key: Optional[str]) -> str:
    """
    Translate any input language into English using a provided OpenAI prompt.
    - If api_key is missing or SDK not available, return original text.
    - Fail-safe: any exception returns original text.
    """
    if not text:
        return text
    if not api_key or not OpenAI:
        return text
    try:
        client = OpenAI(api_key=api_key)
        # Use Responses API with a reusable prompt id provided by the user
        resp = client.responses.create(
            prompt={
                "id": "pmpt_68dc8b8cbdf88190a43f5a45363edc9e07a6358d30f50237",
                "version": "6",
                "variables": {"sentence": text},
            }
        )
        # Extract the text output; handle SDK variations defensively
        content = getattr(resp, "output", None) or getattr(resp, "content", None)
        if isinstance(content, str):
            return content.strip()
        # Some SDK shapes return a list of messages/parts
        try:
            # Try to join all text parts found
            parts = []
            for item in content or []:
                for p in getattr(item, "content", []) or []:
                    val = getattr(p, "text", None) or getattr(p, "value", None)
                    if isinstance(val, str):
                        parts.append(val)
            if parts:
                return "\n".join(parts).strip()
        except Exception:
            pass
        # Last resort: stringify whole object
        return str(resp).strip()
    except Exception:
        return text
