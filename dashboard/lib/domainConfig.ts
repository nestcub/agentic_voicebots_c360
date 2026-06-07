// White-label / vocabulary layer. Reskinning for a different brand or industry = edit this file,
// no component changes. This is what makes the dashboard outsourceable / Chat360-embeddable.

export const domainConfig = {
  brand: "Autovista",
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
};

export function statusBadge(status: string) {
  return domainConfig.statuses[status] ?? { label: status, cls: "bg-slate-100 text-slate-600" };
}

export function commitmentBadge(state: string) {
  return domainConfig.commitmentStates[state] ?? { label: state, cls: "bg-slate-100 text-slate-600" };
}
