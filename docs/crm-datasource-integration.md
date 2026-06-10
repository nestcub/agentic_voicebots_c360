# CRM Data Source Integration Guide

How to wire the dashboard to a direct MySQL / phpMyAdmin CRM database instead of mock data.

---

## How it works

The dashboard uses an adapter pattern. Every page calls `DataSource` interface methods — pages never touch the database directly. Swapping the backend means **creating one new class and wiring it into one factory**. Nothing else changes.

```
Pages / components
      ↓
  useScoped hook          dashboard/lib/useScoped.ts
      ↓
  getDataSource() factory dashboard/lib/dataSource.ts   ← wire here
      ↓
  CrmDataSource           dashboard/lib/sources/crmDataSource.ts  ← create this
      ↓
  MySQL / phpMyAdmin
```

---

## Critical: MySQL cannot be called from the browser

The data hook runs client-side. MySQL connections require server-side code. The pattern is:

1. Create **Next.js API routes** (`/app/api/...`) that run on the server and query MySQL
2. `CrmDataSource` calls those routes via `fetch()`

---

## Step-by-step

### Step 1 — Install mysql2

```bash
cd dashboard
npm install mysql2
```

---

### Step 2 — Create `dashboard/lib/db.ts` (MySQL connection pool)

```ts
// server-only — never import this in client components or pages
import mysql from "mysql2/promise";

export const pool = mysql.createPool({
  host:     process.env.DB_HOST,
  port:     Number(process.env.DB_PORT ?? 3306),
  user:     process.env.DB_USER,
  password: process.env.DB_PASSWORD,
  database: process.env.DB_NAME,
});
```

---

### Step 3 — Create API routes under `dashboard/app/api/`

Create one file per method. Each route queries the CRM table and maps its column names to the TypeScript shapes from `dashboard/lib/types.ts`.

**`dashboard/app/api/leads/route.ts`**
```ts
import { pool } from "@/lib/db";
import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const region = searchParams.get("region");
  const branch = searchParams.get("branch");

  let sql = "SELECT * FROM leads WHERE 1=1";
  const params: string[] = [];
  if (region) { sql += " AND region = ?"; params.push(region); }
  if (branch) { sql += " AND branch = ?"; params.push(branch); }

  const [rows] = await pool.query(sql, params);

  // Map CRM column names → Lead interface (dashboard/lib/types.ts)
  const leads = (rows as any[]).map((r) => ({
    id:               r.id,
    account_id:       r.account_id,
    name:             r.customer_name,   // ← rename to match your CRM columns
    phone:            r.phone_number,
    vehicle_model:    r.vehicle,
    service_due_date: r.service_date,
    source:           r.lead_source,
    region:           r.region,
    branch:           r.branch,
    status:           r.lead_status,     // must be: pending|calling|booked|not_interested|follow_up
    lead_score:       r.score ?? null,
    created_at:       r.created_at,
  }));

  return NextResponse.json(leads);
}
```

**`dashboard/app/api/commitments/route.ts`**
```ts
import { pool } from "@/lib/db";
import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const region = searchParams.get("region");
  const branch = searchParams.get("branch");

  let sql = "SELECT * FROM commitments WHERE 1=1";
  const params: string[] = [];
  if (region) { sql += " AND region = ?"; params.push(region); }
  if (branch) { sql += " AND branch = ?"; params.push(branch); }

  const [rows] = await pool.query(sql, params);

  // Map to Commitment interface (dashboard/lib/types.ts)
  const commitments = (rows as any[]).map((r) => ({
    id:           r.id,
    account_id:   r.account_id,
    lead_id:      r.lead_id,
    region:       r.region,
    branch:       r.branch,
    due_at:       r.due_at,
    goal_context: r.goal_context ?? {},
    note:         r.note ?? "",
    sla_hours:    r.sla_hours ?? 24,
    retries:      r.retries ?? 0,
    max_retries:  r.max_retries ?? 3,
    state:        r.state,               // must be: pending|done|failed
    created_at:   r.created_at,
    updated_at:   r.updated_at,
  }));

  return NextResponse.json(commitments);
}
```

**`dashboard/app/api/call-outcomes/route.ts`**
```ts
import { pool } from "@/lib/db";
import { NextResponse } from "next/server";

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const region = searchParams.get("region");
  const branch = searchParams.get("branch");

  let sql = "SELECT * FROM call_outcomes WHERE 1=1";
  const params: string[] = [];
  if (region) { sql += " AND region = ?"; params.push(region); }
  if (branch) { sql += " AND branch = ?"; params.push(branch); }

  const [rows] = await pool.query(sql, params);

  const outcomes = (rows as any[]).map((r) => ({
    id:           r.id,
    account_id:   r.account_id,
    execution_id: r.execution_id ?? "",
    lead_id:      r.lead_id,
    goal_context: r.goal_context ?? {},
    call_status:  r.call_status,
    outcome:      r.outcome,             // must be: booked|interested|not_interested|callback|no_answer
    duration_sec: r.duration_sec ?? 0,
    callback_at:  r.callback_at ?? null,
    region:       r.region,
    branch:       r.branch,
    created_at:   r.created_at,
  }));

  return NextResponse.json(outcomes);
}
```

**`dashboard/app/api/goal-target/route.ts`**
```ts
import { pool } from "@/lib/db";
import { NextResponse } from "next/server";

export async function GET() {
  const [goalRows] = await pool.query(
    "SELECT * FROM goals WHERE active = 1 LIMIT 1"
  );
  const goal = (goalRows as any[])[0] ?? null;

  const [targetRows] = await pool.query(
    "SELECT * FROM targets WHERE period = ? LIMIT 1",
    [goal?.month ?? new Date().toISOString().slice(0, 7)]
  );
  const target = (targetRows as any[])[0] ?? null;

  return NextResponse.json({ goal, target });
}
```

---

### Step 4 — Create `dashboard/lib/sources/crmDataSource.ts`

```ts
import type { DataSource } from "../dataSource";
import type { Scope, Lead, Commitment, CallOutcome } from "../types";
import { computeKpis, computeTargetProgress, computeReport } from "./compute";

function scopeParams(scope: Scope): string {
  const p = new URLSearchParams();
  if (scope.level === "region" && scope.region) p.set("region", scope.region);
  if (scope.level === "branch" && scope.branch) p.set("branch", scope.branch);
  return p.toString() ? `?${p}` : "";
}

export class CrmDataSource implements DataSource {
  async getAccounts() {
    return [];
  }

  async getLeads(scope: Scope): Promise<Lead[]> {
    const res = await fetch(`/api/leads${scopeParams(scope)}`);
    return res.json();
  }

  async getCommitments(scope: Scope): Promise<Commitment[]> {
    const res = await fetch(`/api/commitments${scopeParams(scope)}`);
    return res.json();
  }

  async getCallOutcomes(scope: Scope): Promise<CallOutcome[]> {
    const res = await fetch(`/api/call-outcomes${scopeParams(scope)}`);
    return res.json();
  }

  async getKpis(scope: Scope) {
    return computeKpis(await this.getLeads(scope));
  }

  async getTargetProgress(scope: Scope) {
    const [leads, commitments, gt] = await Promise.all([
      this.getLeads(scope),
      this.getCommitments(scope),
      this.getGoalAndTarget(scope),
    ]);
    return computeTargetProgress(leads, commitments, gt.target);
  }

  async getReport(scope: Scope, period?: string) {
    const [leads, outcomes, gt] = await Promise.all([
      this.getLeads(scope),
      this.getCallOutcomes(scope),
      this.getGoalAndTarget(scope),
    ]);
    const month = period ?? gt.goal?.month ?? new Date().toISOString().slice(0, 7);
    return computeReport(leads, outcomes, gt.target, scope, month);
  }

  async getGoalAndTarget(_scope: Scope) {
    const res = await fetch("/api/goal-target");
    return res.json();
  }
}
```

---

### Step 5 — Wire CrmDataSource into the factory

In `dashboard/lib/dataSource.ts`, add one new branch:

```ts
// Add BEFORE the existing Supabase check:
if (mode === "crm") {
  const { CrmDataSource } = await import("./sources/crmDataSource");
  _source = new CrmDataSource();
} else if (mode !== "mock" && hasSupabase) {
  ...
```

---

### Step 6 — Set environment variables

Create or edit `dashboard/.env.local`:

```env
NEXT_PUBLIC_DATA_SOURCE=crm

DB_HOST=your-mysql-host-or-ip
DB_PORT=3306
DB_USER=your-db-username
DB_PASSWORD=your-db-password
DB_NAME=your-db-name
```

> **Note:** `DB_*` vars must NOT have the `NEXT_PUBLIC_` prefix — they are server-only secrets and must never be exposed to the browser.

---

## What does NOT need to change

| File | Why untouched |
|---|---|
| All `app/*/page.tsx` files | Pages call `useScoped` — never the DB |
| `dashboard/lib/useScoped.ts` | Hook is backend-agnostic |
| `dashboard/lib/compute.ts` | KPI calculations are pure functions over raw rows |
| `dashboard/lib/types.ts` | Interfaces are the contract — map to them in the API routes |
| All UI components | Completely unaware of data source |

---

## Status value mapping (important)

The dashboard's KPI logic in `compute.ts` checks for these exact status strings:

| Interface value | Meaning |
|---|---|
| `"booked"` or `"interested"` | Counts as a closure / booked lead |
| `"pending"` | Not yet contacted |
| `"calling"` | Currently being called |
| `"not_interested"` | Lost lead |
| `"follow_up"` or `"callback_requested"` | Needs follow-up |

Map your CRM's status values to these in the API route's column mapping (Step 3). If the CRM uses e.g. `"WON"` for booked, translate it: `status: r.crm_status === "WON" ? "booked" : r.crm_status`.
