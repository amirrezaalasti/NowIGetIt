"""OpenRouter client: text LLM + separate multimodal VLM."""

from __future__ import annotations

import base64
import json
import re
from typing import Any, Optional

from openai import OpenAI

from backend.config import Settings, get_settings


class OpenRouterClient:
    """Thin OpenAI-compatible wrapper pointed at OpenRouter."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        if not self.settings.openrouter_api_key:
            raise ValueError(
                "OPENROUTER_API_KEY is required. Set it in the environment."
            )
        self.client = OpenAI(
            api_key=self.settings.openrouter_api_key,
            base_url=self.settings.openrouter_base_url,
            default_headers={
                "HTTP-Referer": self.settings.openrouter_site_url,
                "X-Title": self.settings.openrouter_app_name,
            },
        )
        self.model = self.settings.openrouter_model
        self.vlm_model = self.settings.openrouter_vlm_model

    def chat(
        self,
        *,
        system: str,
        user: str | list[dict[str, Any]],
        temperature: float = 0.4,
        max_tokens: int = 4096,
        json_mode: bool = False,
        model: Optional[str] = None,
    ) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        kwargs: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        return content.strip()

    def chat_json(
        self,
        *,
        system: str,
        user: str | list[dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: int = 4096,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        raw = self.chat(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            model=model,
        )
        return parse_json_object(raw)

    def chat_with_image(
        self,
        *,
        system: str,
        prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/png",
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = True,
    ) -> dict[str, Any] | str:
        """Image review always uses OPENROUTER_VLM_MODEL (multimodal)."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{b64}"},
            },
        ]
        if json_mode:
            return self.chat_json(
                system=system,
                user=user_content,
                temperature=temperature,
                max_tokens=max_tokens,
                model=self.vlm_model,
            )
        return self.chat(
            system=system,
            user=user_content,
            temperature=temperature,
            max_tokens=max_tokens,
            model=self.vlm_model,
        )


def repair_llm_json(text: str) -> str:
    """
    Repair common LLM JSON mistakes — especially unescaped LaTeX
    backslashes like \\frac, \\theta, \\left that cause Invalid \\escape.
    """
    # Drop trailing commas before } or ]
    text = re.sub(r",(\s*[}\]])", r"\1", text)

    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False

    while i < n:
        ch = text[i]

        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue

        # Inside a JSON string
        if ch == '"':
            in_string = False
            out.append(ch)
            i += 1
            continue

        if ch == "\n":
            out.append("\\n")
            i += 1
            continue

        if ch == "\r":
            out.append("\\r")
            i += 1
            continue

        if ch == "\t":
            out.append("\\t")
            i += 1
            continue

        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        # Backslash sequence
        if i + 1 >= n:
            out.append("\\\\")
            i += 1
            continue

        nxt = text[i + 1]

        # Valid unicode escape
        if nxt == "u" and i + 5 < n and all(
            c in "0123456789abcdefABCDEF" for c in text[i + 2 : i + 6]
        ):
            out.append(text[i : i + 6])
            i += 6
            continue

        # Already-escaped backslash or quote or slash
        if nxt in '"\\/':
            out.append(ch)
            out.append(nxt)
            i += 2
            continue

        # \b \f \n \r \t — valid JSON, but often LaTeX (\frac, \theta, \beta…)
        # If more letters follow the escape char, treat as literal LaTeX.
        if nxt in "bfnrt":
            if i + 2 < n and text[i + 2].isalpha():
                out.append("\\\\")
                out.append(nxt)
                i += 2
                continue
            out.append(ch)
            out.append(nxt)
            i += 2
            continue

        # Invalid escape (e.g. \l in \left, \s in \sum) → escape the backslash
        out.append("\\\\")
        i += 1

    return "".join(out)


def extract_first_json_object(text: str) -> str | None:
    """Return the first balanced `{...}` slice, respecting JSON string escapes."""
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _loads_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, ignoring trailing junk after the first value."""
    decoder = json.JSONDecoder()
    data, _end = decoder.raw_decode(text.lstrip())
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating fenced markdown & LaTeX."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    candidates = [cleaned]
    balanced = extract_first_json_object(cleaned)
    if balanced:
        candidates.append(balanced)
    # Fallback: greedy match (may include trailing braces — raw_decode handles it)
    match = re.search(r"\{[\s\S]*\}", cleaned)
    if match:
        candidates.append(match.group(0))

    last_error: Exception | None = None
    seen: set[str] = set()
    for candidate in candidates:
        for variant in (candidate, repair_llm_json(candidate)):
            if variant in seen:
                continue
            seen.add(variant)
            try:
                return _loads_object(variant)
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                continue

    raise ValueError(
        f"Failed to parse model JSON: {last_error}\n---\n{cleaned[:1200]}"
    ) from last_error


def extract_python_code(text: str) -> str:
    """Strip markdown fences from generated Python."""
    if "```python" in text:
        return text.split("```python", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 2:
            return parts[1].strip()
    return text.strip()
