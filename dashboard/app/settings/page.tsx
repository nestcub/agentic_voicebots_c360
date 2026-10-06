import { Card, CardHeader } from "@/components/Card";

type FieldType = "text" | "password" | "time" | "select";

interface SettingsField {
  label: string;
  type: FieldType;
  placeholder?: string;
  options?: string[];
}

interface SettingsSection {
  title: string;
  hint: string;
  fields: SettingsField[];
  actionLabel?: string;
}

const SECTIONS: SettingsSection[] = [
  {
    title: "Workspace",
    hint: "Identity and defaults for this workspace.",
    fields: [
      { label: "Workspace name", type: "text", placeholder: "Autovista Motors" },
      { label: "Industry", type: "text", placeholder: "Automobile" },
      { label: "Default timezone", type: "text", placeholder: "Asia/Kolkata" },
    ],
  },
  {
    title: "API Keys",
    hint: "Credentials for external systems calling into this workspace.",
    fields: [
      { label: "Live API key", type: "password", placeholder: "sk_live_••••••••••••1234" },
      { label: "Test API key", type: "password", placeholder: "sk_test_••••••••••••5678" },
    ],
    actionLabel: "Generate",
  },
  {
    title: "Variables",
    hint: "Global key/value pairs available to every Process Agent.",
    fields: [
      { label: "Variable key", type: "text", placeholder: "brand_name" },
      { label: "Variable value", type: "text", placeholder: "Autovista Motors" },
    ],
    actionLabel: "+ Add Variable",
  },
  {
    title: "Templates",
    hint: "Reusable message templates for WhatsApp, Email and SMS nodes.",
    fields: [
      { label: "Template name", type: "text", placeholder: "Booking Confirmation" },
      { label: "Channel", type: "select", options: ["WhatsApp", "Email", "SMS"] },
    ],
    actionLabel: "+ New Template",
  },
  {
    title: "Business Hours Defaults",
    hint: "Fallback business-hours window applied when a Process doesn't override it.",
    fields: [
      { label: "Timezone", type: "text", placeholder: "Asia/Kolkata" },
      { label: "Start time", type: "time", placeholder: "09:00" },
      { label: "End time", type: "time", placeholder: "18:00" },
    ],
  },
  {
    title: "Webhook Secrets",
    hint: "Signing secret used to validate inbound webhook payloads.",
    fields: [{ label: "Default webhook secret", type: "password", placeholder: "whsec_••••••••••••" }],
    actionLabel: "Rotate Secret",
  },
  {
    title: "General Settings",
    hint: "Workspace-wide locale, currency and notification defaults.",
    fields: [
      { label: "Default locale", type: "text", placeholder: "en-IN" },
      { label: "Default currency", type: "text", placeholder: "INR" },
      { label: "Notification email", type: "text", placeholder: "ops@autovista.example" },
    ],
  },
];

function ComingSoonBadge() {
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-accent/10 text-accent border border-accent/20">
      Coming soon
    </span>
  );
}

function SettingsField({ field }: { field: SettingsField }) {
  const baseClass =
    "w-full px-3 py-2 rounded-lg border border-border bg-surface-container text-sm text-text-muted placeholder:text-text-muted cursor-not-allowed";
  return (
    <div>
      <label className="block text-xs font-medium text-text-muted mb-1">{field.label}</label>
      {field.type === "select" ? (
        <select disabled className={baseClass} defaultValue="">
          <option value="" disabled>
            {field.options?.[0]}
          </option>
          {field.options?.map((opt) => (
            <option key={opt}>{opt}</option>
          ))}
        </select>
      ) : (
        <input
          type={field.type}
          disabled
          placeholder={field.placeholder}
          className={baseClass}
        />
      )}
    </div>
  );
}

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-on-surface">Settings</h1>

      <Card className="p-4 border-primary/30 bg-primary/5">
        <p className="text-sm text-on-surface">
          Settings are read-only in this preview — configuration happens per-Agent in the Add Agent wizard for
          now.
        </p>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {SECTIONS.map((section) => (
          <Card key={section.title} className="p-0">
            <div className="flex items-start justify-between gap-2">
              <CardHeader title={section.title} hint={section.hint} />
              <div className="pt-4 pr-5">
                <ComingSoonBadge />
              </div>
            </div>
            <div className="px-5 pb-5 space-y-4">
              {section.fields.map((field) => (
                <SettingsField key={field.label} field={field} />
              ))}
              {section.actionLabel && (
                <button
                  disabled
                  className="px-4 py-2 rounded-lg text-sm font-medium bg-surface-container text-text-muted border border-border cursor-not-allowed"
                >
                  {section.actionLabel}
                </button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
