import * as XLSX from "xlsx";

export interface ParsedLead {
  name: string;
  phone: string;
  vehicle_model: string;
  service_due_date: string;
  region: string;
  branch: string;
  lead_type: string;
  lead_sub_type: string;
}

export interface ParseResult {
  leads: ParsedLead[];
  errors: string[];
  total_rows: number;
}

const REQUIRED_COLS = ["Name", "Phone", "Region", "Branch"];
const OPTIONAL_COLS = ["Vehicle Model", "Service Due Date", "Lead Type", "Lead Sub Type"];

export function parseXlsxBuffer(buffer: Buffer | ArrayBuffer): ParseResult {
  const wb = XLSX.read(buffer, { type: "buffer" });
  const ws = wb.Sheets[wb.SheetNames[0]];
  const rows: Record<string, string>[] = XLSX.utils.sheet_to_json(ws, { defval: "" });

  if (rows.length === 0) {
    return { leads: [], errors: ["File is empty or has no data rows"], total_rows: 0 };
  }

  const errors: string[] = [];
  const headers = Object.keys(rows[0]);
  const missing = REQUIRED_COLS.filter(c => !headers.includes(c));
  if (missing.length > 0) {
    errors.push(`Missing required columns: ${missing.join(", ")}`);
    return { leads: [], errors, total_rows: rows.length };
  }

  const leads: ParsedLead[] = [];
  rows.forEach((row, i) => {
    const rowNum = i + 2;
    if (!row["Name"]?.trim()) { errors.push(`Row ${rowNum}: Name is empty`); return; }
    if (!row["Phone"]?.trim()) { errors.push(`Row ${rowNum}: Phone is empty`); return; }
    leads.push({
      name: String(row["Name"]).trim(),
      phone: String(row["Phone"]).trim(),
      vehicle_model: String(row["Vehicle Model"] ?? "").trim(),
      service_due_date: String(row["Service Due Date"] ?? "").trim(),
      region: String(row["Region"] ?? "").trim(),
      branch: String(row["Branch"] ?? "").trim(),
      lead_type: String(row["Lead Type"] ?? "other").trim().toLowerCase(),
      lead_sub_type: String(row["Lead Sub Type"] ?? "").trim().toLowerCase(),
    });
  });

  return { leads, errors, total_rows: rows.length };
}
