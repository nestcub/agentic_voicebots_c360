"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader } from "@/components/Card";
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

function SaveCancelButtons({
  onSave,
  onCancel,
  saving,
  saveLabel = "Save",
}: {
  onSave: () => void;
  onCancel: () => void;
  saving: boolean;
  saveLabel?: string;
}) {
  return (
    <div className="flex items-center gap-2 justify-end pt-1">
      <button
        onClick={onCancel}
        disabled={saving}
        className="px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-text-muted hover:bg-surface-container disabled:opacity-60 transition-colors"
      >
        Cancel
      </button>
      <button
        onClick={onSave}
        disabled={saving}
        className="px-3 py-1.5 rounded-lg text-xs font-medium bg-primary text-on-primary hover:bg-primary-container disabled:opacity-60 transition-colors"
      >
        {saving ? "Saving…" : saveLabel}
      </button>
    </div>
  );
}

function BotForm({ draft, onChange }: { draft: VoiceBotWrite; onChange: (draft: VoiceBotWrite) => void }) {
  const [didsText, setDidsText] = useState((draft.dids ?? []).join(", "));

  return (
    <div className="space-y-3">
      <div className="grid sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-text-muted mb-1">Label</label>
          <input
            value={draft.label ?? ""}
            onChange={(e) => onChange({ ...draft, label: e.target.value })}
            placeholder="Sales Bot"
            className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1">Communication Type</label>
          <select
            value={draft.communication_type ?? ""}
            onChange={(e) => onChange({ ...draft, communication_type: e.target.value })}
            className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
          >
            <option value="">—</option>
            {Object.entries(COMMUNICATION_TYPE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1">Bot Name</label>
          <input
            value={draft.bot_name ?? ""}
            onChange={(e) => onChange({ ...draft, bot_name: e.target.value })}
            className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-text-muted mb-1">Bot ID</label>
          <input
            value={draft.bot_id ?? ""}
            onChange={(e) => onChange({ ...draft, bot_id: e.target.value })}
            className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
          />
        </div>
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">Bot DID/s (comma-separated)</label>
        <input
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
          className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm"
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">API URL</label>
        <input
          value={draft.api_url ?? ""}
          onChange={(e) => onChange({ ...draft, api_url: e.target.value })}
          placeholder={DEFAULT_OUTBOUND_API_URL}
          className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-sm font-mono"
        />
      </div>
      <div>
        <label className="block text-xs text-text-muted mb-1">
          Script / curl <span className="text-text-muted">(reference only — not executed)</span>
        </label>
        <textarea
          value={draft.script ?? ""}
          onChange={(e) => onChange({ ...draft, script: e.target.value })}
          rows={4}
          spellCheck={false}
          className="w-full px-2.5 py-1.5 rounded-lg border border-border bg-surface text-xs font-mono"
        />
      </div>
    </div>
  );
}

function BotRow({ bot, onSaved, onDeleted }: { bot: VoiceBot; onSaved: () => void; onDeleted: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<VoiceBotWrite>(botToDraft(bot));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function startEditing() {
    setDraft(botToDraft(bot));
    setError(null);
    setEditing(true);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await updateVoiceBot(bot.id, draft);
      onSaved();
      setEditing(false);
    } catch (e) {
      setError(errorMessage(e, "Failed to update bot"));
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm(`Remove bot "${bot.label || bot.bot_name || bot.id}"?`)) return;
    setSaving(true);
    setError(null);
    try {
      await deleteVoiceBot(bot.id);
      onDeleted();
    } catch (e) {
      setError(errorMessage(e, "Failed to remove bot — it may still be in use by a process agent"));
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <div className="rounded-lg border border-border p-4 bg-surface-container">
        {error && <p className="text-xs text-bad mb-1">{error}</p>}
        <div className="flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-on-surface">{bot.label || bot.bot_name || `Bot ${bot.id}`}</p>
          <div className="flex items-center gap-3">
            <button onClick={startEditing} className="text-xs text-primary hover:underline">
              Edit
            </button>
            <button
              onClick={handleDelete}
              disabled={saving}
              className="text-xs text-bad hover:underline disabled:opacity-60"
            >
              Remove
            </button>
          </div>
        </div>
        <div className="mt-2 space-y-0.5 text-xs text-text-muted">
          {bot.communication_type && (
            <p>{COMMUNICATION_TYPE_LABELS[bot.communication_type] || bot.communication_type}</p>
          )}
          <p>
            {bot.bot_name || "—"}
            {bot.bot_id && <span className="ml-1">({bot.bot_id})</span>}
          </p>
          {bot.dids.length > 0 && <p>DIDs: {bot.dids.join(", ")}</p>}
          {bot.api_url && <p className="font-mono break-all">{bot.api_url}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border p-4 space-y-2">
      {error && <p className="text-xs text-bad">{error}</p>}
      <BotForm draft={draft} onChange={setDraft} />
      <SaveCancelButtons onSave={handleSave} onCancel={() => setEditing(false)} saving={saving} />
    </div>
  );
}

export default function BotsPage() {
  const [bots, setBots] = useState<VoiceBot[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [adding, setAdding] = useState(false);
  const [newDraft, setNewDraft] = useState<VoiceBotWrite>(emptyDraft());
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

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

  async function handleCreate() {
    setCreating(true);
    setCreateError(null);
    try {
      await createVoiceBot(newDraft);
      setAdding(false);
      setNewDraft(emptyDraft());
      refresh();
    } catch (e) {
      setCreateError(errorMessage(e, "Failed to create bot"));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-lg font-semibold text-on-surface">Bots</h1>
        <p className="text-xs text-text-muted mt-0.5">
          Reusable bot identities — pick one for a process agent at creation time instead of typing it in.
        </p>
      </div>

      <Card className="p-5 space-y-4">
        <div className="flex items-start justify-between gap-3">
          <CardHeader
            title="Voice Bots"
            hint={bots ? `${bots.length} bot${bots.length === 1 ? "" : "s"}` : undefined}
          />
          {!adding && (
            <button
              onClick={() => {
                setCreateError(null);
                setNewDraft(emptyDraft());
                setAdding(true);
              }}
              className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium bg-primary text-on-primary hover:bg-primary-container transition-colors"
            >
              + Add Bot
            </button>
          )}
        </div>

        {error && <p className="text-xs text-bad">{error}</p>}

        {loading && !bots ? (
          <div className="h-24 bg-surface-container rounded-lg animate-pulse" />
        ) : bots && bots.length === 0 && !adding ? (
          <p className="text-sm text-text-muted">No bots yet — add one to attach it to a process agent.</p>
        ) : (
          <div className="space-y-3">
            {bots?.map((bot) => (
              <BotRow key={bot.id} bot={bot} onSaved={refresh} onDeleted={refresh} />
            ))}
          </div>
        )}

        {adding && (
          <div className="rounded-lg border border-dashed border-border p-4 space-y-3">
            {createError && <p className="text-xs text-bad">{createError}</p>}
            <BotForm draft={newDraft} onChange={setNewDraft} />
            <SaveCancelButtons
              onSave={handleCreate}
              onCancel={() => setAdding(false)}
              saving={creating}
              saveLabel="Create Bot"
            />
          </div>
        )}
      </Card>
    </div>
  );
}
