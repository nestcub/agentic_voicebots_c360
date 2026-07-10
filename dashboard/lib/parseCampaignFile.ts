import * as XLSX from "xlsx";

export interface ParsedCampaignFile {
  headers: string[];
  rows: Record<string, string>[];
  errors: string[];
}

export function parseCampaignFile(buffer: ArrayBuffer, filename: string): ParsedCampaignFile {
  try {
    const isCsv = filename.toLowerCase().endsWith(".csv");
    const wb = isCsv
      ? XLSX.read(new TextDecoder().decode(buffer), { type: "string" })
      : XLSX.read(buffer, { type: "array" });

    const ws = wb.Sheets[wb.SheetNames[0]];
    const rawRows: Record<string, unknown>[] = XLSX.utils.sheet_to_json(ws, { defval: "" });

    if (rawRows.length === 0) {
      return { headers: [], rows: [], errors: ["File is empty or has no data rows"] };
    }

    const headers = Object.keys(rawRows[0]);
    const rows: Record<string, string>[] = rawRows.map(row => {
      const coerced: Record<string, string> = {};
      for (const key of Object.keys(row)) {
        coerced[key] = String(row[key]).trim();
      }
      return coerced;
    });

    return { headers, rows, errors: [] };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return { headers: [], rows: [], errors: [`Could not parse file: ${message}`] };
  }
}
