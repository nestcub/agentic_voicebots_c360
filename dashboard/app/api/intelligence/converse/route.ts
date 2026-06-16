import { NextRequest, NextResponse } from "next/server";

const BASE = process.env.INTEL_API_URL ?? "http://localhost:8001";
const KEY = process.env.INTEL_API_KEY ?? "";
const parsedTimeout = Number(process.env.INTEL_CONVERSE_TIMEOUT_MS ?? "180000");
const UPSTREAM_TIMEOUT_MS =
  Number.isFinite(parsedTimeout) && parsedTimeout > 0 ? parsedTimeout : 180_000;

function safeParseJson(value: string): unknown | null {
  if (!value) return null;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

function extractMessage(payload: unknown, fallback: string): string {
  if (typeof payload === "string" && payload.trim()) return payload.trim();

  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const candidates = [
      record.message,
      record.error,
      record.detail,
      record.details,
    ];

    for (const candidate of candidates) {
      if (typeof candidate === "string" && candidate.trim()) {
        return candidate.trim();
      }

      if (candidate && typeof candidate === "object") {
        const nested = extractMessage(candidate, "");
        if (nested) return nested;
      }
    }
  }

  return fallback;
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), UPSTREAM_TIMEOUT_MS);

    let res: Response;
    try {
      res = await fetch(`${BASE}/converse`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": KEY,
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return NextResponse.json(
          {
            status: 504,
            message: `Intelligence backend timed out after ${UPSTREAM_TIMEOUT_MS / 1000}s.`,
          },
          { status: 504 },
        );
      }

      return NextResponse.json(
        {
          status: 502,
          message:
            error instanceof Error && error.message
              ? error.message
              : "Unable to reach the intelligence backend.",
        },
        { status: 502 },
      );
    } finally {
      clearTimeout(timeoutId);
    }

    const raw = await res.text();
    const parsed = safeParseJson(raw);

    if (!res.ok) {
      const errorPayload =
        parsed && typeof parsed === "object" ? (parsed as Record<string, unknown>) : null;
      return NextResponse.json(
        {
          status: res.status,
          message: extractMessage(
            parsed ?? raw,
            `Intelligence backend returned ${res.status}${res.statusText ? ` ${res.statusText}` : ""}.`,
          ),
          ...(errorPayload?.code ? { code: errorPayload.code } : {}),
          ...(errorPayload?.metadata ? { metadata: errorPayload.metadata } : {}),
        },
        { status: res.status },
      );
    }

    if (parsed !== null) {
      return NextResponse.json(parsed, { status: res.status });
    }

    return NextResponse.json(
      raw ? { reply: raw } : {},
      { status: res.status },
    );
  } catch (error) {
    if (error instanceof SyntaxError) {
      return NextResponse.json(
        {
          status: 400,
          message: "Invalid request body.",
        },
        { status: 400 },
      );
    }

    return NextResponse.json(
      {
        status: 500,
        message:
          error instanceof Error && error.message
            ? error.message
            : "Unexpected proxy error.",
      },
      { status: 500 },
    );
  }
}
