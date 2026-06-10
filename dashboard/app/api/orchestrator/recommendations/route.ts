import { NextRequest, NextResponse } from "next/server";
import { DispatchRecommendation } from "@/lib/types";

// Module-level store — exported so [id] sub-route can import and mutate it
export const recommendationsStore = new Map<string, DispatchRecommendation>();

// Seed with demo data on module load
const seed1: DispatchRecommendation = {
  id: "rec-demo-001",
  account_id: "demo",
  campaign_id: "camp-demo-001",
  campaign_name: "Monsoon Service Campaign",
  qualified_count: 847,
  estimated_call_minutes: 2541,
  dids_available: 6,
  status: "pending_approval",
  scheduled_at: null,
  approved_at: null,
  recommendation_summary:
    "847 leads qualify for outreach. AI filtered out 203 leads (dead status or duplicate phone). Recommended call window: Mon–Fri 10am–6pm. At 6 DIDs with avg 3 min/call, estimated completion in ~7 hours of call time.",
  created_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(), // 30 min ago
};

const seed2: DispatchRecommendation = {
  id: "rec-demo-002",
  account_id: "demo",
  campaign_id: "camp-demo-002",
  campaign_name: "Q2 Sales Push",
  qualified_count: 312,
  estimated_call_minutes: 936,
  dids_available: 6,
  status: "done",
  scheduled_at: null,
  approved_at: new Date(Date.now() - 1000 * 60 * 60 * 48).toISOString(),
  recommendation_summary:
    "312 leads dispatched. 89 booked, 145 not interested, 78 pending follow-up.",
  created_at: new Date(Date.now() - 1000 * 60 * 60 * 50).toISOString(),
};

recommendationsStore.set(seed1.id, seed1);
recommendationsStore.set(seed2.id, seed2);

export async function GET() {
  const sorted = Array.from(recommendationsStore.values()).sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  return NextResponse.json(sorted);
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { campaign_id, campaign_name, total_leads } = body as {
    campaign_id: string;
    campaign_name: string;
    total_leads: number;
  };

  const qualified_count = Math.round(total_leads * 0.85);
  const estimated_call_minutes = qualified_count * 3;
  const filtered_out = total_leads - qualified_count;
  const hours_estimate = Math.ceil(estimated_call_minutes / 60);

  const recommendation: DispatchRecommendation = {
    id: "rec-" + crypto.randomUUID().slice(0, 8),
    account_id: "demo",
    campaign_id,
    campaign_name,
    qualified_count,
    estimated_call_minutes,
    dids_available: 6,
    status: "pending_approval",
    scheduled_at: null,
    approved_at: null,
    recommendation_summary: `${qualified_count} leads qualify for outreach. AI filtered out ${filtered_out} leads (dead status or duplicate phone). At 6 DIDs with avg 3 min/call, estimated completion in ~${hours_estimate} hours of call time.`,
    created_at: new Date().toISOString(),
  };

  recommendationsStore.set(recommendation.id, recommendation);
  return NextResponse.json(recommendation, { status: 201 });
}
