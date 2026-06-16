"""Provider-agnostic LLM client — Anthropic and OpenAI."""

import json
import os

from dotenv import load_dotenv

load_dotenv()


class LLMCompletionError(RuntimeError):
    """Structured LLM completion failure with provider metadata."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "llm_completion_failed",
        provider: str | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
        finish_reason: str | None = None,
        metadata: dict | None = None,
        raw_text: str | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.provider = provider
        self.model = model
        self.max_tokens = max_tokens
        self.finish_reason = finish_reason
        self.metadata = metadata or {}
        self.raw_text = raw_text

    def to_dict(self) -> dict:
        payload = {
            "code": self.code,
            "message": self.message,
        }
        metadata = {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "finish_reason": self.finish_reason,
            **self.metadata,
        }
        metadata = {k: v for k, v in metadata.items() if v is not None}
        if metadata:
            payload["metadata"] = metadata
        return payload


class LLMClient:
    """Wraps LLM provider calls behind a uniform complete / complete_json interface."""

    def __init__(self, provider: str = None):
        """Load provider, model, and API key from env; raise ValueError if missing."""
        self.provider = (provider or os.getenv("LLM_PROVIDER", "anthropic")).lower()
        self.last_usage = None
        self.last_completion_metadata = {}

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

    @staticmethod
    def _get_attr(value, name: str, default=None):
        """Read a field from SDK objects or dicts without depending on one shape."""
        if value is None:
            return default
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @staticmethod
    def _normalize_finish_reason(reason) -> str | None:
        if reason is None:
            return None
        return str(reason).lower()

    def _record_completion_metadata(self, response, max_tokens: int) -> dict:
        """Capture common completion metadata across providers for later error handling."""
        metadata = {
            "provider": self.provider,
            "model": self._get_attr(response, "model", self.model) or self.model,
            "max_tokens": max_tokens,
        }
        if self.provider == "anthropic":
            metadata["finish_reason"] = self._normalize_finish_reason(
                self._get_attr(response, "stop_reason")
            )
        else:
            choice = None
            choices = self._get_attr(response, "choices", []) or []
            if choices:
                choice = choices[0]
            metadata["finish_reason"] = self._normalize_finish_reason(
                self._get_attr(choice, "finish_reason")
            )
        self.last_usage = self._get_attr(response, "usage")
        self.last_completion_metadata = metadata
        return metadata

    def _build_completion_error(
        self,
        message: str,
        *,
        code: str,
        max_tokens: int,
        raw_text: str | None = None,
        metadata: dict | None = None,
    ) -> LLMCompletionError:
        completion_metadata = {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": max_tokens,
            **(self.last_completion_metadata or {}),
        }
        return LLMCompletionError(
            message,
            code=code,
            provider=completion_metadata.get("provider"),
            model=completion_metadata.get("model"),
            max_tokens=completion_metadata.get("max_tokens"),
            finish_reason=completion_metadata.get("finish_reason"),
            metadata=metadata,
            raw_text=raw_text,
        )

    @staticmethod
    def _looks_like_truncated_json(text: str) -> bool:
        """Conservatively detect incomplete JSON without flagging ordinary malformed payloads."""
        stripped = text.strip()
        if not stripped or stripped[0] not in "{[":
            return False

        stack = []
        in_string = False
        escape = False

        for ch in stripped:
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
            elif ch in "{[":
                stack.append(ch)
            elif ch == "}":
                if not stack or stack[-1] != "{":
                    return False
                stack.pop()
            elif ch == "]":
                if not stack or stack[-1] != "[":
                    return False
                stack.pop()

        if in_string or escape or stack:
            return True
        return stripped.endswith((",", ":"))

    @staticmethod
    def _finish_reason_hit_token_limit(finish_reason: str | None) -> bool:
        return finish_reason in {"length", "max_tokens", "max_output_tokens", "model_length"}

    def _response_was_truncated(self, raw_text: str) -> bool:
        finish_reason = self.last_completion_metadata.get("finish_reason")
        if self._finish_reason_hit_token_limit(finish_reason):
            return True
        return self._looks_like_truncated_json(self._extract_json(raw_text))

    def complete(self, system, user: str, max_tokens: int = 4096, cache_system: bool = True) -> str:
        """Send system + user prompt; return assistant text as string.

        system may be:
          - str: wrapped in a single cached block (Anthropic) or plain string (OpenAI)
          - list of {"text": str, "cache": bool}: Anthropic cache-control blocks; flattened for OpenAI
        """
        self.last_usage = None
        self.last_completion_metadata = {
            "provider": self.provider,
            "model": self.model,
            "max_tokens": max_tokens,
            "finish_reason": None,
        }
        try:
            if self.provider == "anthropic":
                if isinstance(system, list):
                    system_param = []
                    for b in system:
                        if not b.get("text"):
                            continue
                        block = {"type": "text", "text": b["text"]}
                        if b.get("cache"):
                            cc = {"type": "ephemeral"}
                            if b.get("ttl"):
                                cc["ttl"] = b["ttl"]
                            block["cache_control"] = cc
                        system_param.append(block)
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
                self._record_completion_metadata(response, max_tokens)
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
                self._record_completion_metadata(response, max_tokens)
                return response.choices[0].message.content or ""

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
                self._record_completion_metadata(response, max_tokens)
                return response.choices[0].message.content or ""

            raise NotImplementedError(f"complete() not implemented for '{self.provider}'.")
        except LLMCompletionError:
            raise
        except Exception as exc:
            raise self._build_completion_error(
                "LLM provider request failed.",
                code="llm_provider_error",
                max_tokens=max_tokens,
                metadata={"error": str(exc)},
            ) from exc

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
        """Send prompt expecting JSON; parse and return as dict.

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
        except json.JSONDecodeError as exc:
            if self._response_was_truncated(raw):
                raise self._build_completion_error(
                    "LLM response was truncated before it could return complete JSON.",
                    code="llm_json_truncated",
                    max_tokens=max_tokens,
                    raw_text=raw,
                    metadata={"parse_error": str(exc), "attempt": 1},
                ) from exc
            retry_user = (
                user
                + "\n\nYour previous response was not valid JSON. "
                "Return ONLY a valid JSON object — no markdown, no extra text."
            )
            raw = self.complete(json_system, retry_user, max_tokens)
            try:
                return json.loads(self._extract_json(raw))
            except json.JSONDecodeError as retry_exc:
                if self._response_was_truncated(raw):
                    raise self._build_completion_error(
                        "LLM response was truncated before it could return complete JSON.",
                        code="llm_json_truncated",
                        max_tokens=max_tokens,
                        raw_text=raw,
                        metadata={"parse_error": str(retry_exc), "attempt": 2},
                    ) from retry_exc
                raise self._build_completion_error(
                    "LLM returned malformed JSON after a retry.",
                    code="llm_json_invalid",
                    max_tokens=max_tokens,
                    raw_text=raw,
                    metadata={"parse_error": str(retry_exc), "attempt": 2},
                ) from retry_exc
