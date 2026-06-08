"""Provider-agnostic LLM client. Tonight: Anthropic only. Tomorrow: add Azure OpenAI."""

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

        # Tomorrow: Azure OpenAI
        # elif self.provider == "azure":
        #     from openai import AzureOpenAI
        #     self._client = AzureOpenAI(
        #         api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        #         api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        #         azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        #     )
        #     self.model = os.getenv("AZURE_OPENAI_DEPLOYMENT")

        else:
            raise ValueError(
                f"Unsupported LLM provider: '{self.provider}'. Supported: 'anthropic'."
            )

    def complete(self, system, user: str, max_tokens: int = 4096, cache_system: bool = True) -> str:
        """Send system + user prompt; return assistant text as string.

        system may be:
          - str: wrapped in a single cached block (as before)
          - list of {"text": str, "cache": bool}: each block rendered with optional cache_control
        The large canvas reference (block 1) and platform knowledge (block 2) are both marked
        cache=True so each warms its own cache breakpoint. Max 4 breakpoints — we use 2.
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
