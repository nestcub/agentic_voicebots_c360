"""Provider-agnostic embedding module. Default: Gemini gemini-embedding-001 (768 dims via output_dimensionality).
To switch to OpenAI: set EMBEDDING_PROVIDER=openai, EMBEDDING_MODEL=text-embedding-3-small, EMBEDDING_DIM=1536.
"""

import os
from dotenv import load_dotenv

load_dotenv()

_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "gemini").lower()
_MODEL    = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
_DIM      = int(os.getenv("EMBEDDING_DIM", "768"))

_client = None

def _get_client():
    global _client
    if _client is not None:
        return _client
    if _PROVIDER == "gemini":
        from google import genai
        _client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    elif _PROVIDER == "openai":
        from openai import OpenAI
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    else:
        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: '{_PROVIDER}'. Use 'gemini' or 'openai'.")
    return _client


def embed(text: str) -> list[float]:
    """Embed a single text string. Returns a list of floats of length EMBEDDING_DIM."""
    client = _get_client()
    if _PROVIDER == "gemini":
        from google.genai import types
        result = client.models.embed_content(
            model=_MODEL, contents=text,
            config=types.EmbedContentConfig(output_dimensionality=_DIM),
        )
        vec = result.embeddings[0].values
    elif _PROVIDER == "openai":
        result = client.embeddings.create(model=_MODEL, input=text)
        vec = result.data[0].embedding
    assert len(vec) == _DIM, f"Embedding dim mismatch: got {len(vec)}, expected {_DIM}. Check EMBEDDING_DIM env var."
    return list(vec)


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Batches to API where supported; falls back to sequential."""
    if not texts:
        return []
    client = _get_client()
    if _PROVIDER == "gemini":
        from google.genai import types
        cfg = types.EmbedContentConfig(output_dimensionality=_DIM)
        result = client.models.embed_content(model=_MODEL, contents=texts, config=cfg)
        vecs = [e.values for e in result.embeddings]
    elif _PROVIDER == "openai":
        result = client.embeddings.create(model=_MODEL, input=texts)
        vecs = [item.embedding for item in sorted(result.data, key=lambda x: x.index)]
    return [list(v) for v in vecs]
