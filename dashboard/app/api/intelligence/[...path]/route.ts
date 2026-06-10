import { NextRequest, NextResponse } from "next/server";

const BASE = process.env.INTEL_API_URL ?? "http://localhost:8001";
const KEY = process.env.INTEL_API_KEY ?? "";

type Ctx = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, ctx: Ctx): Promise<NextResponse> {
  const { path } = await ctx.params;
  const target = new URL(`${BASE}/${path.join("/")}`);
  req.nextUrl.searchParams.forEach((v, k) => target.searchParams.set(k, v));

  const headers: Record<string, string> = { "x-api-key": KEY };
  let body: string | undefined;

  if (req.method !== "GET" && req.method !== "DELETE") {
    const json = await req.json().catch(() => ({}));
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }

  const res = await fetch(target.toString(), { method: req.method, headers, body });
  const data = await res.json().catch(() => ({}));
  return NextResponse.json(data, { status: res.status });
}

export const GET = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const POST = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const DELETE = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
export const PATCH = (req: NextRequest, ctx: Ctx) => proxy(req, ctx);
