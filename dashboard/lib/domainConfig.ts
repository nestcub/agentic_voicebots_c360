// White-label / vocabulary layer. Reskinning for a different brand or industry = edit this file,
// no component changes. This is what makes the dashboard outsourceable / Chat360-embeddable.

export const domainConfig = {
  brand: "Hyundai",
  // Shown beside the header greeting; hidden if the file isn't in public/ yet.
  logo: "/hyundai-logo.png",
  product: "AI Orchestrator",
  industry: "automobile",

  // Metric labels (swap "Test Drives" / "Service Booked" wording per brand)
  metrics: {
    totalLeads: "Total Leads",
    booked: "Service / Sales Booked",
    followUps: "Follow-ups",
    conversion: "Conversion",
    reachOut: "Reach-outs",
    close: "Closures",
  },

  // Lead status vocabulary + colors (Tailwind classes)
  statuses: {
    pending:           { label: "Pending",        cls: "bg-blue-100 text-blue-700" },
    calling:           { label: "Calling",        cls: "bg-sky-100 text-sky-700" },
    booked:            { label: "Booked",         cls: "bg-emerald-100 text-emerald-700" },
    interested:        { label: "Interested",     cls: "bg-emerald-100 text-emerald-700" },
    callback_requested:{ label: "Callback",       cls: "bg-amber-100 text-amber-700" },
    follow_up:         { label: "Follow-up",      cls: "bg-amber-100 text-amber-700" },
    not_interested:    { label: "Not Interested", cls: "bg-rose-100 text-rose-700" },
    no_answer:         { label: "No Answer",      cls: "bg-slate-100 text-slate-600" },
  } as Record<string, { label: string; cls: string }>,

  // Commitment ledger states (follow-up SLA view)
  commitmentStates: {
    pending:        { label: "Pending",        cls: "bg-amber-100 text-amber-700" },
    done:           { label: "Done",           cls: "bg-emerald-100 text-emerald-700" },
    not_interested: { label: "Not Interested", cls: "bg-rose-100 text-rose-700" },
    exhausted:      { label: "Exhausted",      cls: "bg-rose-100 text-rose-700" },
    cancelled:      { label: "Cancelled",      cls: "bg-slate-100 text-slate-600" },
  } as Record<string, { label: string; cls: string }>,

  vehicleField: "vehicle_model",
  regions: ["Mumbai", "Pune"],
  branchesByRegion: {
    Mumbai: ["Andheri", "Borivali", "Goregaon", "Worli", "Thane", "Vashi", "Kharghar", "Panvel"],
    Pune: ["Wakad", "Hinjewadi", "Kothrud", "Hadapsar", "Baner", "Pimpri-Chinchwad", "Viman Nagar"],
  } as Record<string, string[]>,

  // Display-only renames for backend names (usernames, org names) until they're renamed in the DB.
  // Keys are matched case-insensitively.
  displayAliases: {
    hyundaistaff: "hyundai.hq",
    "hyundai poc": "Hyundai",
  } as Record<string, string>,

  // Dealer board on a voice agent's Calls tab: calls are grouped by their
  // `assigned_dealer_name` disposition, matched against `dealer` below.
  dealers: {
    field: "assigned_dealer_name",
    location: "Delhi",
    // Show frontend-only sample calls (lib/demoCalls.ts) for dealers with no real calls yet.
    demoCalls: true,
    outlets: [
      { area: "Arjan Garh Chhatarpur", dealer: "Ramaa Hyundai" },
      { area: "Badarpur", dealer: "Shuban Sai Hyundai" },
      { area: "Dilshad Garden", dealer: "Himgiri Hyundai" },
      { area: "East Patel Nagar", dealer: "Bagga Link Hyundai" },
      { area: "Janakpuri", dealer: "Triumph Hyundai" },
      { area: "Kailash Colony", dealer: "Koncept Hyundai" },
      { area: "Lajpat Nagar IV", dealer: "Ramaa Hyundai" },
      { area: "Malviya Nagar", dealer: "Lamba Hyundai" },
      { area: "Mangolpuri", dealer: "Deep Hyundai" },
      { area: "Mother Dairy", dealer: "Sunrise Hyundai" },
      { area: "Moti Nagar", dealer: "Hans Hyundai" },
      { area: "Mundka", dealer: "Deep Hyundai" },
      { area: "Narela", dealer: "Malwa Hyundai" },
      { area: "Nazafgarh", dealer: "Universal Hyundai" },
      { area: "Okhla", dealer: "Koncept Hyundai" },
      { area: "Patparganj", dealer: "Sunrise Hyundai" },
      { area: "Roop Nagar", dealer: "Pahwa Hyundai" },
      { area: "Safdarjang Enclave", dealer: "Koncept Hyundai" },
      { area: "Sarasvati Vihar", dealer: "Malwa Hyundai" },
      { area: "Shalimar Place", dealer: "Unity Hyundai" },
      { area: "Wazirpur", dealer: "Lamba Hyundai" },
      { area: "Rohini", dealer: "Deep Hyundai" },
    ],
  },
};

export function displayName(name: string): string {
  return domainConfig.displayAliases[name.trim().toLowerCase()] ?? name;
}

export function statusBadge(status: string) {
  return domainConfig.statuses[status] ?? { label: status, cls: "bg-slate-100 text-slate-600" };
}

export function commitmentBadge(state: string) {
  return domainConfig.commitmentStates[state] ?? { label: state, cls: "bg-slate-100 text-slate-600" };
}
