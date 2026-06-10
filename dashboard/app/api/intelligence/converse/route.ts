import { NextRequest, NextResponse } from "next/server";

const BASE = process.env.INTEL_API_URL ?? "http://localhost:8001";
const KEY = process.env.INTEL_API_KEY ?? "";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const res = await fetch(`${BASE}/converse`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": KEY,
    },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  return NextResponse.json(data, { status: res.status });
}
