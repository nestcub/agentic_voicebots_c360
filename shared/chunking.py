"""Window diarized transcript segments into coherent 'call moments' for embedding."""


def chunk_segments(segments: list[dict], window: int = 4, overlap: int = 1) -> list[dict]:
    """Group consecutive segments into overlapping windows.

    segments: [{"speaker","role","start","end","text"}, ...]
    Returns: [{"chunk_index","role_sequence","start","end","text"}, ...]
      - text: the windowed segments joined as "ROLE: <text>" lines
      - role_sequence: e.g. "CUSTOMER>AGENT"
      - start/end: from first/last segment in the window
    window = segments per chunk; overlap = shared segments between adjacent chunks
    """
    # Filter out empty/whitespace text segments
    filtered = [s for s in segments if s.get("text", "").strip()]

    if not filtered:
        return []

    step = window - overlap
    chunks = []
    chunk_index = 0
    i = 0

    while i < len(filtered):
        window_segs = filtered[i : i + window]

        role_sequence = ">".join(s["role"] for s in window_segs)
        text = "\n".join(f"{s['role']}: {s['text']}" for s in window_segs)
        start = window_segs[0]["start"]
        end = window_segs[-1]["end"]

        chunks.append(
            {
                "chunk_index": chunk_index,
                "role_sequence": role_sequence,
                "start": start,
                "end": end,
                "text": text,
            }
        )

        chunk_index += 1
        i += step

        # If this was a partial chunk (fewer than window segments), we're done
        if len(window_segs) < window:
            break

    return chunks
