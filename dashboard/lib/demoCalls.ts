// Frontend-only sample calls so every dealer on the dashboard has something to show.
// Nothing here touches the backend; turn it off with domainConfig.dealers.demoCalls.
// Rows carry variables.is_demo = "true" and negative ids so they never collide with real executions.

import { DEALERS, matchDealer } from "@/components/process-agents/DealersSection";
import { domainConfig } from "@/lib/domainConfig";
import type { CallRow } from "@/lib/types";

const FIRST_NAMES = [
  "Rahul", "Priya", "Amit", "Neha", "Vikram", "Anjali", "Rohit", "Sneha", "Arjun", "Pooja",
  "Karan", "Divya", "Sanjay", "Ritu", "Manish", "Kavita", "Aditya", "Meera", "Nikhil", "Swati",
];
const LAST_NAMES = [
  "Sharma", "Verma", "Gupta", "Malhotra", "Kapoor", "Singh", "Arora", "Chopra", "Bansal", "Mehta",
  "Khanna", "Agarwal", "Sethi", "Bhatia", "Jain",
];
const MODELS = ["Creta", "Venue", "Verna", "i20", "Exter", "Alcazar", "Tucson", "Grand i10 Nios", "Aura", "Ioniq 5"];
// Weighted toward positive, as most inbound enquiries are.
const SENTIMENTS = ["positive", "positive", "positive", "neutral", "neutral", "negative"];

// Small deterministic PRNG so the sample set is identical on every load.
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function pick<T>(r: () => number, list: T[]): T {
  return list[Math.floor(r() * list.length)];
}

/** Sample calls (2–4 each) for every dealer that has no real call in `rows`. */
export function demoCallsFor(rows: CallRow[]): CallRow[] {
  if (!domainConfig.dealers.demoCalls) return [];
  const field = domainConfig.dealers.field;
  const covered = new Set(
    rows.map((row) => String(row.variables[field] ?? "").trim()).filter(Boolean).map((v) => matchDealer(v).key),
  );

  const now = Date.now();
  const out: CallRow[] = [];
  DEALERS.forEach((dealer, d) => {
    if (covered.has(dealer.key)) return;
    const r = rng(d + 1);
    const count = 2 + Math.floor(r() * 3);
    for (let i = 0; i < count; i++) {
      const area = dealer.areas[i % dealer.areas.length];
      const phone = `+9198${String(Math.floor(r() * 1e8)).padStart(8, "0")}`;
      const minutesAgo = Math.floor(r() * 7 * 24 * 60);
      const id = -(d * 10 + i + 1);
      out.push({
        id,
        lead_id: `demo-${d}-${i}`,
        status: "completed",
        campaign_id: "demo",
        duration: 60 + Math.floor(r() * 240),
        current_node: "Completed",
        created_at: new Date(now - minutesAgo * 60_000).toISOString(),
        variables: {
          customer_name: `${pick(r, FIRST_NAMES)} ${pick(r, LAST_NAMES)}`,
          to_number: phone,
          model_of_interest: pick(r, MODELS),
          sentiment: pick(r, SENTIMENTS),
          [field]: `${dealer.name}, ${area}`,
          is_demo: "true",
        },
        whatsapp: null,
        suggested_template: null,
      });
    }
  });
  return out;
}
