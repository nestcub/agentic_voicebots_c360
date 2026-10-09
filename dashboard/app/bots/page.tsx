"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Bot, Check, Copy, Pencil, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardAction } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { PageHeader } from "@/components/common/PageHeader";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { ToneBadge } from "@/components/StatusBadge";
import {
  listVoiceBots,
  createVoiceBot,
  updateVoiceBot,
  deleteVoiceBot,
  type VoiceBotWrite,
} from "@/lib/telehubApi";
import type { VoiceBot } from "@/lib/types";
import { COMMUNICATION_TYPE_LABELS, errorMessage } from "@/components/process-agents/shared";

// Trailing slash required — without it Chat360 307-redirects here (see
// services/telehub/apps/telehub/services/dispatcher.py, which follows it
// anyway as a safety net, but there's no reason to rely on that for new bots).
const DEFAULT_OUTBOUND_API_URL = "https://app.chat360.io/api/voicebot/outbound/";

function emptyDraft(): VoiceBotWrite {
  return {
    label: "",
    communication_type: "voice_outbound",
    bot_name: "",
    bot_id: "",
    dids: [],
    api_url: "",
    script: "",
  };
}

function botToDraft(bot: VoiceBot): VoiceBotWrite {
  return {
    label: bot.label,
    communication_type: bot.communication_type,
    bot_name: bot.bot_name,
    bot_id: bot.bot_id,
    dids: bot.dids,
    api_url: bot.api_url,
    script: bot.script,
  };
}

function botTitle(bot: VoiceBot): string {
  return bot.label || bot.bot_name || `Bot ${bot.id}`;
}

function Field({ label, htmlFor, children }: { label: React.ReactNode; htmlFor: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function BotForm({ draft, onChange }: { draft: VoiceBotWrite; onChange: (draft: VoiceBotWrite) => void }) {
  const [didsText, setDidsText] = useState((draft.dids ?? []).join(", "));

  return (
    <div className="space-y-4">
      <div className="grid sm:grid-cols-2 gap-4">
        <Field label="Label" htmlFor="bot-label">
          <Input
            id="bot-label"
            value={draft.label ?? ""}
            onChange={(e) => onChange({ ...draft, label: e.target.value })}
            placeholder="Sales Bot"
          />
        </Field>
        <Field label="Communication Type" htmlFor="bot-type">
          <NativeSelect
            id="bot-type"
            value={draft.communication_type ?? ""}
            onChange={(e) => onChange({ ...draft, communication_type: e.target.value })}
          >
            <NativeSelectOption value="">—</NativeSelectOption>
            {Object.entries(COMMUNICATION_TYPE_LABELS).map(([value, label]) => (
              <NativeSelectOption key={value} value={value}>
                {label}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Bot Name" htmlFor="bot-name">
          <Input
            id="bot-name"
            value={draft.bot_name ?? ""}
            onChange={(e) => onChange({ ...draft, bot_name: e.target.value })}
          />
        </Field>
        <Field label="Bot ID" htmlFor="bot-id">
          <Input id="bot-id" value={draft.bot_id ?? ""} onChange={(e) => onChange({ ...draft, bot_id: e.target.value })} />
        </Field>
      </div>
      <Field label="Bot DID/s (comma-separated)" htmlFor="bot-dids">
        <Input
          id="bot-dids"
          value={didsText}
          onChange={(e) => {
            setDidsText(e.target.value);
            onChange({
              ...draft,
              dids: e.target.value
                .split(",")
                .map((v) => v.trim())
                .filter(Boolean),
            });
          }}
          placeholder="+91XXXXXXXXXX"
        />
      </Field>
      <Field label="API URL" htmlFor="bot-api-url">
        <Input
          id="bot-api-url"
          value={draft.api_url ?? ""}
          onChange={(e) => onChange({ ...draft, api_url: e.target.value })}
          placeholder={DEFAULT_OUTBOUND_API_URL}
          className="font-mono text-xs"
        />
      </Field>
      <Field
        label={
          <>
            Script / curl <span className="font-normal">(reference only — not executed)</span>
          </>
        }
        htmlFor="bot-script"
      >
        <Textarea
          id="bot-script"
          value={draft.script ?? ""}
          onChange={(e) => onChange({ ...draft, script: e.target.value })}
          rows={4}
          spellCheck={false}
          className="font-mono text-xs"
        />
      </Field>
    </div>
  );
}

// Add and edit share one dialog: `bot` null means "create".
function BotDialog({
  open,
  bot,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  bot: VoiceBot | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<VoiceBotWrite>(emptyDraft());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDraft(bot ? botToDraft(bot) : emptyDraft());
    setError(null);
  }, [open, bot]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      if (bot) {
        await updateVoiceBot(bot.id, draft);
        toast.success(`Saved "${draft.label || draft.bot_name || "bot"}"`);
      } else {
        await createVoiceBot(draft);
        toast.success(`Created "${draft.label || draft.bot_name || "bot"}"`);
      }
      onSaved();
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e, bot ? "Failed to update bot" : "Failed to create bot"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !saving && onOpenChange(o)}>
      <DialogContent className="sm:max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{bot ? `Edit ${botTitle(bot)}` : "Add Voicebot"}</DialogTitle>
          <DialogDescription>
            A reusable bot identity — pick it for a process agent instead of typing it in.
          </DialogDescription>
        </DialogHeader>
        {error && <ErrorAlert message={error} />}
        {/* Keyed so the DIDs text box re-initialises for each bot. */}
        {open && <BotForm key={bot?.id ?? "new"} draft={draft} onChange={setDraft} />}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving && <Spinner />}
            {bot ? "Save" : "Create Bot"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          variant="ghost"
          size="icon-xs"
          aria-label="Copy"
          onClick={() => {
            navigator.clipboard
              .writeText(value)
              .then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              })
              .catch(() => toast.error("Couldn't copy to clipboard"));
          }}
        >
          {copied ? <Check className="text-ok" /> : <Copy />}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{copied ? "Copied" : "Copy"}</TooltipContent>
    </Tooltip>
  );
}

function BotCard({ bot, onEdit, onRemove }: { bot: VoiceBot; onEdit: () => void; onRemove: () => void }) {
  return (
    <Card className="gap-4">
      <CardHeader className="flex flex-row items-start gap-3">
        <div className="w-10 h-10 shrink-0 rounded-xl bg-accent text-primary flex items-center justify-center">
          <Bot className="w-5 h-5" />
        </div>
        <div className="min-w-0 space-y-1.5">
          <CardTitle className="truncate">{botTitle(bot)}</CardTitle>
          {bot.communication_type && (
            <ToneBadge tone="info" className="normal-case">
              {COMMUNICATION_TYPE_LABELS[bot.communication_type] || bot.communication_type}
            </ToneBadge>
          )}
        </div>
        <CardAction className="flex gap-1">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon-sm" onClick={onEdit} aria-label="Edit">
                <Pencil />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Edit</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={onRemove}
                aria-label="Remove"
                className="text-muted-foreground hover:text-bad"
              >
                <Trash2 />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Remove</TooltipContent>
          </Tooltip>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <div className="grid grid-cols-[5rem_1fr] gap-y-2 gap-x-3 items-center">
          <span className="text-xs text-muted-foreground">Bot name</span>
          <span className="truncate">{bot.bot_name || "—"}</span>
          <span className="text-xs text-muted-foreground">Bot ID</span>
          <span className="flex items-center gap-1 min-w-0">
            <span className="font-mono text-xs truncate">{bot.bot_id || "—"}</span>
            {bot.bot_id && <CopyButton value={bot.bot_id} />}
          </span>
          <span className="text-xs text-muted-foreground">DIDs</span>
          <span className="flex flex-wrap gap-1">
            {bot.dids.length > 0 ? (
              bot.dids.map((did) => (
                <span key={did} className="px-2 py-0.5 rounded-md bg-muted font-mono text-xs">
                  {did}
                </span>
              ))
            ) : (
              <span className="text-muted-foreground">—</span>
            )}
          </span>
        </div>
        {bot.api_url && (
          <div className="flex items-center gap-1 rounded-lg bg-muted px-2.5 py-1.5">
            <span className="font-mono text-xs text-muted-foreground truncate flex-1">{bot.api_url}</span>
            <CopyButton value={bot.api_url} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function BotsPage() {
  const [bots, setBots] = useState<VoiceBot[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingBot, setEditingBot] = useState<VoiceBot | null>(null);

  const [removingBot, setRemovingBot] = useState<VoiceBot | null>(null);
  const [removing, setRemoving] = useState(false);

  function refresh() {
    setLoading(true);
    setError(null);
    listVoiceBots()
      .then((data) => setBots(data))
      .catch((e) => setError(errorMessage(e, "Failed to load bots")))
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    refresh();
  }, []);

  function openCreate() {
    setEditingBot(null);
    setDialogOpen(true);
  }

  function openEdit(bot: VoiceBot) {
    setEditingBot(bot);
    setDialogOpen(true);
  }

  async function handleRemove() {
    if (!removingBot) return;
    setRemoving(true);
    try {
      await deleteVoiceBot(removingBot.id);
      toast.success(`Removed "${botTitle(removingBot)}"`);
      setRemovingBot(null);
      refresh();
    } catch (e) {
      toast.error(errorMessage(e, "Failed to remove bot — it may still be in use by a process agent"));
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Bot}
        title="Voicebots"
        description="Reusable bot identities — pick one for a process agent at creation time instead of typing it in."
        badges={bots && <ToneBadge tone="muted" className="normal-case">{bots.length} total</ToneBadge>}
        actions={
          <Button onClick={openCreate}>
            <Plus /> Add Voicebot
          </Button>
        }
      />

      {error && <ErrorAlert message={error} action={<Button variant="outline" size="sm" onClick={refresh}>Retry</Button>} />}

      {loading && !bots ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-52 rounded-xl" />
          ))}
        </div>
      ) : bots && bots.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="No voicebots yet"
          description="Add one to attach it to a process agent."
          action={
            <Button onClick={openCreate}>
              <Plus /> Add Voicebot
            </Button>
          }
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {bots?.map((bot) => (
            <BotCard key={bot.id} bot={bot} onEdit={() => openEdit(bot)} onRemove={() => setRemovingBot(bot)} />
          ))}
        </div>
      )}

      <BotDialog open={dialogOpen} bot={editingBot} onOpenChange={setDialogOpen} onSaved={refresh} />

      <AlertDialog open={removingBot !== null} onOpenChange={(o) => !o && !removing && setRemovingBot(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remove {removingBot ? botTitle(removingBot) : "bot"}?</AlertDialogTitle>
            <AlertDialogDescription>
              This deletes the bot identity. It can&apos;t be removed while a process agent still uses it.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={removing}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={(e) => {
                e.preventDefault();
                handleRemove();
              }}
              disabled={removing}
              className="bg-destructive text-white hover:bg-destructive/90"
            >
              {removing && <Spinner />}
              Remove
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

