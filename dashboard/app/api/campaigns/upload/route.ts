import { NextRequest, NextResponse } from "next/server";
import { parseXlsxBuffer, type ParsedLead } from "../../../../lib/parseXlsx";
import type { Lead, UploadResult } from "../../../../lib/types";

// Module-level store so Wave 3 pages can retrieve campaign data via getCampaignUpload()
const campaignStore = new Map<string, { uploadResult: UploadResult; leads: Lead[] }>();

export function getCampaignUpload(campaign_id: string) {
  return campaignStore.get(campaign_id) ?? null;
}

function toCampaignName(filename: string): string {
  // Strip extension
  const base = filename.replace(/\.[^.]+$/, "");
  // Replace dashes and underscores with spaces
  const spaced = base.replace(/[-_]+/g, " ");
  // Title-case each word
  return spaced
    .split(" ")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

export async function POST(req: NextRequest) {
  let formData: FormData;
  try {
    formData = await req.formData();
  } catch {
    return NextResponse.json({ error: "Invalid multipart/form-data request" }, { status: 400 });
  }

  const file = formData.get("file");
  if (!file || !(file instanceof File)) {
    return NextResponse.json({ error: "No file provided. Send a multipart field named 'file'." }, { status: 400 });
  }

  const arrayBuffer = await file.arrayBuffer();

  const { leads: parsedLeads, errors, total_rows } = parseXlsxBuffer(arrayBuffer);

  // Return 400 only if there are errors AND no leads were parsed at all
  if (errors.length > 0 && parsedLeads.length === 0) {
    return NextResponse.json(
      { error: "Failed to parse file", errors, total_rows },
      { status: 400 }
    );
  }

  const campaign_id = crypto.randomUUID();
  const campaign_name = toCampaignName(file.name);

  const now = new Date().toISOString();

  const leads: Lead[] = parsedLeads.map((pl: ParsedLead) => ({
    id: crypto.randomUUID(),
    account_id: "demo",
    name: pl.name,
    phone: pl.phone,
    vehicle_model: pl.vehicle_model,
    service_due_date: pl.service_due_date,
    source: "xlsx",
    region: pl.region,
    branch: pl.branch,
    status: "pending",
    lead_score: null,
    created_at: now,
  }));

  const preview_leads = leads.slice(0, 5);

  const uploadResult: UploadResult = {
    campaign_id,
    campaign_name,
    total_leads: parsedLeads.length,
    preview_leads,
    errors,
  };

  campaignStore.set(campaign_id, { uploadResult, leads });

  return NextResponse.json(uploadResult, { status: 200 });
}
