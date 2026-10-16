// Small building blocks shared by the Settings tab's sections (SettingsTab.tsx
// and OmnichannelSection.tsx).
import { Pencil, type LucideIcon } from "lucide-react";
import { Card } from "@/components/Card";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

export const INPUT_CLASS =
  "w-full px-2.5 py-1.5 rounded-md border border-input bg-card shadow-xs outline-none transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 text-sm";

export function SettingsRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start gap-2 text-sm">
      <span className="text-muted-foreground min-w-40">{label}</span>
      <span className="text-foreground break-words">{value}</span>
    </div>
  );
}

export function SettingsSection({
  title,
  hint,
  icon: Icon,
  actions,
  children,
}: {
  title: string;
  hint?: string;
  icon?: LucideIcon;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Card className="p-5 space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          {Icon && (
            <span className="w-9 h-9 shrink-0 rounded-lg bg-accent text-primary flex items-center justify-center">
              <Icon className="w-4 h-4" />
            </span>
          )}
          <div className="min-w-0">
            <p className="text-base font-semibold text-foreground">{title}</p>
            {hint && <p className="text-xs text-muted-foreground mt-0.5">{hint}</p>}
          </div>
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      <div className="space-y-2">{children}</div>
    </Card>
  );
}

export function EmptySection({ label }: { label: string }) {
  return <p className="text-sm text-muted-foreground">{label}</p>;
}

export function EditButton({ onClick }: { onClick: () => void }) {
  return (
    <Button variant="outline" size="sm" onClick={onClick}>
      <Pencil /> Edit
    </Button>
  );
}

export function SaveCancelButtons({
  onSave,
  onCancel,
  saving,
}: {
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  return (
    <>
      <Button variant="outline" size="sm" onClick={onCancel} disabled={saving}>
        Cancel
      </Button>
      <Button size="sm" onClick={onSave} disabled={saving}>
        {saving && <Spinner />}
        Save
      </Button>
    </>
  );
}
