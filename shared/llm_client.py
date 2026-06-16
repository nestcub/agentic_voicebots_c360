"""Provider-agnostic LLM client — Anthropic and OpenAI."""

import json
import os

from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    """Wraps LLM provider calls behind a uniform complete / complete_json interface."""

    def __init__(self, provider: str = None):
        """Load provider, model, and API key from env; raise ValueError if missing."""
        self.provider = (provider or os.getenv("LLM_PROVIDER", "anthropic")).lower()

        if self.provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is not set in environment.")
            self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)

        elif self.provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY is not set in environment.")
            self.model = os.getenv("OPENAI_INSIGHT_MODEL", "gpt-4.1")
            from openai import OpenAI
            self._client = OpenAI(api_key=api_key)

        elif self.provider == "azure":
            api_key = os.getenv("AZURE_OPENAI_API_KEY")
            azure_endpoint = os.getenv("AZURE_OPENAI_BASE_URL")
            if not api_key or not azure_endpoint:
                raise ValueError("AZURE_OPENAI_API_KEY and AZURE_OPENAI_BASE_URL must be set in environment.")
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
            self.model = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1")
            from openai import AzureOpenAI
            self._client = AzureOpenAI(api_key=api_key, azure_endpoint=azure_endpoint, api_version=api_version)

        else:
            raise ValueError(
                f"Unsupported LLM provider: '{self.provider}'. Supported: 'anthropic', 'openai', 'azure'."
            )

    def complete(self, system, user: str, max_tokens: int = 4096, cache_system: bool = True) -> str:
        """Send system + user prompt; return assistant text as string.

        system may be:
          - str: wrapped in a single cached block (Anthropic) or plain string (OpenAI)
          - list of {"text": str, "cache": bool}: Anthropic cache-control blocks; flattened for OpenAI
        """
        if self.provider == "anthropic":
            if isinstance(system, list):
                system_param = [
                    {"type": "text", "text": b["text"],
                     **({"cache_control": {"type": "ephemeral"}} if b.get("cache") else {})}
                    for b in system if b.get("text")
                ]
            elif cache_system and system:
                system_param = [{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }]
            else:
                system_param = system
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_param,
                messages=[{"role": "user", "content": user}],
            )
            self.last_usage = getattr(response, "usage", None)
            return response.content[0].text

        elif self.provider == "openai":
            # Flatten list-of-blocks to plain string — OpenAI doesn't use cache blocks
            sys_text = system if isinstance(system, str) else "\n\n".join(
                b["text"] for b in system if b.get("text")
            )
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": sys_text},
                           {"role": "user",   "content": user}],
            )
            return response.choices[0].message.content

        elif self.provider == "azure":
            sys_text = system if isinstance(system, str) else "\n\n".join(
                b["text"] for b in system if b.get("text")
            )
            response = self._client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=[{"role": "system", "content": sys_text},
                           {"role": "user",   "content": user}],
            )
            return response.choices[0].message.content

        raise NotImplementedError(f"complete() not implemented for '{self.provider}'.")

    @staticmethod
    def _extract_json(text: str) -> str:
        """Strip markdown fences and extract the outermost JSON object or array."""
        import re
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if fenced:
            return fenced.group(1).strip()
        for open_c, close_c in [('{', '}'), ('[', ']')]:
            start = text.find(open_c)
            end   = text.rfind(close_c)
            if start != -1 and end > start:
                return text[start:end + 1]
        return text.strip()

    def complete_json(self, system, user: str, max_tokens: int = 4096) -> dict:
        """Send prompt expecting JSON; parse and return as dict, retrying once on failure.

        system may be str or list of {"text": str, "cache": bool} blocks.
        For list: JSON instruction is appended to the last block's text so the cache
        boundary on the knowledge block stays intact (suffix is constant → still cacheable).
        """
        _JSON_SUFFIX = "\n\nRespond with valid JSON only. No markdown fences, no explanation."
        if isinstance(system, list):
            json_system = system[:-1] + [{**system[-1], "text": system[-1]["text"] + _JSON_SUFFIX}]
        else:
            json_system = system + _JSON_SUFFIX
        raw = self.complete(json_system, user, max_tokens)
        try:
            return json.loads(self._extract_json(raw))
        except json.JSONDecodeError:
            retry_user = (
                user
                + "\n\nYour previous response was not valid JSON. "
                "Return ONLY a valid JSON object — no markdown, no extra text."
            )
            raw = self.complete(json_system, retry_user, max_tokens)
            return json.loads(self._extract_json(raw))
