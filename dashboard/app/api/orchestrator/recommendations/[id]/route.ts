import { NextRequest, NextResponse } from "next/server";
import { recommendationsStore } from "../route";

export async function POST(
  req: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await req.json();
  const { action } = body as { action: string; scheduled_at?: string };

  const recommendation = recommendationsStore.get(id);
  if (!recommendation) {
    return NextResponse.json({ ok: false, error: "Not found" }, { status: 404 });
  }

  switch (action) {
    case "approve":
      recommendation.status = "approved";
      recommendation.approved_at = new Date().toISOString();
      recommendationsStore.set(id, recommendation);
      return NextResponse.json({ ok: true, recommendation });

    case "schedule": {
      const { scheduled_at } = body as { scheduled_at?: string };
      recommendation.status = "scheduled";
      recommendation.scheduled_at = scheduled_at ?? null;
      recommendationsStore.set(id, recommendation);
      return NextResponse.json({ ok: true, recommendation });
    }

    case "cancel":
      recommendation.status = "cancelled";
      recommendationsStore.set(id, recommendation);
      return NextResponse.json({ ok: true, recommendation });

    default:
      return NextResponse.json(
        { ok: false, error: "Unknown action" },
        { status: 400 }
      );
  }
}
