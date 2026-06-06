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

    def complete(self, system: str, user: str, max_tokens: int = 4096) -> str:
        """Send system + user prompt; return assistant text as string."""
        if self.provider == "anthropic":
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text
        raise NotImplementedError(f"complete() not implemented for '{self.provider}'.")

    def complete_json(self, system: str, user: str, max_tokens: int = 4096) -> dict:
        """Send prompt expecting JSON; parse and return as dict, retrying once on failure."""
        json_system = system + "\n\nRespond with valid JSON only. No markdown fences, no explanation."
        raw = self.complete(json_system, user, max_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            retry_user = (
                user
                + "\n\nYour previous response was not valid JSON. "
                "Return ONLY a valid JSON object — no markdown, no extra text."
            )
            raw = self.complete(json_system, retry_user, max_tokens)
            return json.loads(raw)
