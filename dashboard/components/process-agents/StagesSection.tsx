// Settings → Voicebots & stages: the voicebot(s) a process agent runs, which of
// each bot's numbers a stage uses, and the hand-offs that pass a finished
// call's results on to the next stage. Backed by /journeys/ and
// /journey-transitions/ (services/telehub/apps/telehub/services/stages.py).
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowRight, ArrowUp, Bot, Pencil, Plus, Trash2 } from "lucide-react";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";
import type { BotJourney, JourneyTransition, ProcessAgentDetail, VoiceBot } from "@/lib/types";
import {
  createJourneyTransition,
  createStage,
  deleteJourneyTransition,
  deleteStage,
  listJourneyTransitions,
  listVoiceBots,
  updateJourneyTransition,
  updateStage,
} from "@/lib/telehubApi";
import { ChecksEditor, cleanChecks, describeChecks } from "./ChecksEditor";
import { EmptySection, INPUT_CLASS, SaveCancelButtons, SettingsSection } from "./SettingsPrimitives";
import { COMMUNICATION_TYPE_LABELS, apiErrorText } from "./shared";

const VARIABLE_LIST_ID = "stage-variable-keys";

function botName(bot: VoiceBot | null): string {
  return bot ? bot.label || bot.bot_name || `Voice bot ${bot.id}` : "No voice bot";
}

// ── Stage form (add / change bot) ────────────────────────────────────────

function StageForm({
  agentId,
  stage,
  bots,
  onSaved,
  onCancel,
}: {
  agentId: number;
  stage: BotJourney | null;
  bots: VoiceBot[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(stage?.name ?? "");
  const [botId, setBotId] = useState<number | "">(stage?.voice_bot?.id ?? bots[0]?.id ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (botId === "") {
      setError("Choose a voice bot.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = { name: name.trim(), voice_bot: Number(botId) };
      if (stage) await updateStage(agentId, stage.id, body);
      else await createStage(agentId, body);
      onSaved();
    } catch (e) {
      setError(apiErrorText(e, "Failed to save stage"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-primary/40 p-3 space-y-3">
      {error && <p className="text-xs text-bad">{error}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Stage name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Follow-up"
            maxLength={128}
            className={INPUT_CLASS}
          />
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Voice bot</label>
          <select
            value={botId}
            onChange={(e) => setBotId(e.target.value ? Number(e.target.value) : "")}
            className={INPUT_CLASS}
          >
            {bots.length === 0 && <option value="">Create a voice bot first</option>}
            {bots.map((b) => (
              <option key={b.id} value={b.id}>
                {botName(b)} ({COMMUNICATION_TYPE_LABELS[b.communication_type] || b.communication_type || "bot"})
              </option>
            ))}
          </select>
        </div>
      </div>
      {stage && (
        <p className="text-[11px] text-muted-foreground">Changing the bot resets which of its numbers this stage uses.</p>
      )}
      {!stage && (
        <p className="text-[11px] text-muted-foreground">
          A new stage starts with the same retry, business-hours and QA settings as the first stage.
        </p>
      )}
      <div className="flex items-center gap-2">
        <SaveCancelButtons onSave={handleSave} onCancel={onCancel} saving={saving} />
      </div>
    </div>
  );
}

// ── Stage card ───────────────────────────────────────────────────────────

function StageCard({
  agentId,
  stage,
  index,
  busy,
  onChanged,
  onError,
  onEdit,
  onDelete,
  canDelete,
}: {
  agentId: number;
  stage: BotJourney;
  index: number;
  busy: boolean;
  onChanged: () => void;
  onError: (message: string | null) => void;
  onEdit: () => void;
  onDelete: () => void;
  canDelete: boolean;
}) {
  const bot = stage.voice_bot;
  const botNumbers = bot?.numbers ?? [];
  const hasAssigned = stage.numbers.length > 0;
  const isInbound = bot?.communication_type === "voice_inbound";
  const [saving, setSaving] = useState(false);

  // A stage is assigned one of its bot's numbers; "" = automatic.
  async function assignNumber(value: string) {
    setSaving(true);
    onError(null);
    try {
      await updateStage(agentId, stage.id, { numbers: value ? [Number(value)] : [] });
      onChanged();
    } catch (e) {
      onError(apiErrorText(e, "Failed to assign number"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-border p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-foreground">
            <span className="text-muted-foreground font-mono mr-1.5">{index + 1}.</span>
            {stage.name}
          </p>
          <p className="text-xs text-muted-foreground">
            {botName(bot)}
            {bot?.communication_type && (
              <span> · {COMMUNICATION_TYPE_LABELS[bot.communication_type] || bot.communication_type}</span>
            )}
            {bot?.bot_name && bot.bot_name !== bot.label && <span> · {bot.bot_name}</span>}
          </p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <Button variant="outline" size="sm" onClick={onEdit} disabled={busy}>
            <Pencil /> Edit
          </Button>
          {canDelete && (
            <Button variant="outline" size="sm" onClick={onDelete} disabled={busy} aria-label={`Remove ${stage.name}`}>
              <Trash2 />
            </Button>
          )}
        </div>
      </div>

      {botNumbers.length === 0 ? (
        <p className="text-xs text-muted-foreground">
          This bot has no numbers yet — add them on the{" "}
          <Link href="/bots" className="text-primary hover:underline">
            Voicebots page
          </Link>
          .
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <label className="text-xs text-muted-foreground">
            {isInbound ? "Number customers dial" : "Dial from number"}
          </label>
          <select
            value={hasAssigned ? stage.numbers[0].id : ""}
            disabled={saving || busy}
            onChange={(e) => assignNumber(e.target.value)}
            className={`${INPUT_CLASS} w-auto font-mono text-xs`}
          >
            <option value="">Automatic{botNumbers[0] ? ` (${botNumbers[0].did})` : ""}</option>
            {botNumbers.map((n) => (
              <option key={n.id} value={n.id}>
                {n.did}
              </option>
            ))}
          </select>
          <span className="text-[11px] text-muted-foreground">
            {isInbound
              ? !hasAssigned
                ? "Calls to any of the bot's numbers are accepted; others are flagged."
                : "Calls to any other number are flagged as a wrong number."
              : "Outbound calls use this as the caller ID."}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Hand-off form ────────────────────────────────────────────────────────

function TransitionForm({
  agentId,
  transition,
  stages,
  onSaved,
  onCancel,
}: {
  agentId: number;
  transition: JourneyTransition | null;
  stages: BotJourney[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [from, setFrom] = useState<number | "">(transition?.from_journey ?? stages[0]?.id ?? "");
  const [to, setTo] = useState<number | "">(transition?.to_journey ?? stages[1]?.id ?? "");
  const [on, setOn] = useState<"completed" | "retries_exhausted">(transition?.on ?? "completed");
  const [match, setMatch] = useState<"all" | "any">(transition?.match ?? "all");
  const [checks, setChecks] = useState(transition?.checks ?? []);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSave() {
    if (from === "" || to === "") {
      setError("Choose both stages.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = { from_journey: Number(from), to_journey: Number(to), on, match, checks: cleanChecks(checks) };
      if (transition) await updateJourneyTransition(agentId, transition.id, body);
      else await createJourneyTransition(agentId, body);
      onSaved();
    } catch (e) {
      setError(apiErrorText(e, "Failed to save hand-off"));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rounded-lg border border-primary/40 p-3 space-y-3">
      {error && <p className="text-xs text-bad">{error}</p>}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <div>
          <label className="block text-xs text-muted-foreground mb-1">From stage</label>
          <select value={from} onChange={(e) => setFrom(Number(e.target.value))} className={INPUT_CLASS}>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Hand over to</label>
          <select value={to} onChange={(e) => setTo(Number(e.target.value))} className={INPUT_CLASS}>
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-muted-foreground mb-1">Moment</label>
          <select value={on} onChange={(e) => setOn(e.target.value as typeof on)} className={INPUT_CLASS}>
            <option value="completed">A call finishes</option>
            <option value="retries_exhausted">Retries run out (never connected)</option>
          </select>
        </div>
      </div>
      <ChecksEditor
        checks={checks}
        match={match}
        onChecks={setChecks}
        onMatch={setMatch}
        variableListId={VARIABLE_LIST_ID}
        heading="Only when"
        emptyHint="No conditions — every lead is handed over."
      />
      <div className="flex items-center gap-2">
        <SaveCancelButtons onSave={handleSave} onCancel={onCancel} saving={saving} />
      </div>
    </div>
  );
}

// ── Section ──────────────────────────────────────────────────────────────

export function StagesSection({ agent, onSaved }: { agent: ProcessAgentDetail; onSaved: () => void }) {
  const agentId = agent.id;
  const stages = [...agent.bot_journeys].sort((a, b) => a.order - b.order || a.id - b.id);
  const variableKeys = agent.variables.map((v) => v.key);

  const [bots, setBots] = useState<VoiceBot[]>([]);
  const [transitions, setTransitions] = useState<JourneyTransition[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [editingStage, setEditingStage] = useState<number | "new" | null>(null);
  const [editingTransition, setEditingTransition] = useState<number | "new" | null>(null);
  const [pendingDeleteStage, setPendingDeleteStage] = useState<BotJourney | null>(null);
  const [pendingDeleteTransition, setPendingDeleteTransition] = useState<JourneyTransition | null>(null);

  const refreshTransitions = useCallback(async () => {
    try {
      setTransitions(await listJourneyTransitions(agentId));
    } catch (e) {
      setError(apiErrorText(e, "Failed to load hand-offs"));
    }
  }, [agentId]);

  useEffect(() => {
    refreshTransitions();
  }, [refreshTransitions, agent.bot_journeys.length]);

  useEffect(() => {
    listVoiceBots()
      .then(setBots)
      .catch(() => {});
  }, []);

  async function confirmDeleteStage() {
    const target = pendingDeleteStage;
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await deleteStage(agentId, target.id);
      onSaved();
      await refreshTransitions();
    } catch (e) {
      setError(apiErrorText(e, "Failed to remove stage"));
    } finally {
      setBusy(false);
      setPendingDeleteStage(null);
    }
  }

  async function confirmDeleteTransition() {
    const target = pendingDeleteTransition;
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await deleteJourneyTransition(agentId, target.id);
      await refreshTransitions();
    } catch (e) {
      setError(apiErrorText(e, "Failed to remove hand-off"));
    } finally {
      setBusy(false);
      setPendingDeleteTransition(null);
    }
  }

  async function moveTransition(index: number, direction: -1 | 1) {
    if (!transitions) return;
    const target = index + direction;
    if (target < 0 || target >= transitions.length) return;
    const order = [...transitions];
    [order[index], order[target]] = [order[target], order[index]];
    setBusy(true);
    setError(null);
    try {
      // Renumber the whole list so ties in the old priorities can't leave the order ambiguous.
      await Promise.all(
        order.map((t, position) => (t.priority === position ? null : updateJourneyTransition(agentId, t.id, { priority: position }))),
      );
      await refreshTransitions();
    } catch (e) {
      setError(apiErrorText(e, "Failed to reorder hand-offs"));
    } finally {
      setBusy(false);
    }
  }

  const stageChanged = () => {
    setEditingStage(null);
    onSaved();
  };

  return (
    <SettingsSection
      icon={Bot}
      title="Voicebots & stages"
      hint="Each stage runs one voicebot. A finished call can hand the lead on to the next stage."
      actions={
        <Link href="/bots" className={buttonVariants({ variant: "outline", size: "sm" })}>
          Manage bots <ArrowRight />
        </Link>
      }
    >
      <datalist id={VARIABLE_LIST_ID}>
        {variableKeys.map((key) => (
          <option key={key} value={key} />
        ))}
      </datalist>
      {error && <p className="text-xs text-bad">{error}</p>}

      <div className="space-y-2">
        {stages.length === 0 && <EmptySection label="No voicebot stage yet." />}
        {stages.map((stage, index) =>
          editingStage === stage.id ? (
            <StageForm
              key={stage.id}
              agentId={agentId}
              stage={stage}
              bots={bots}
              onSaved={stageChanged}
              onCancel={() => setEditingStage(null)}
            />
          ) : (
            <StageCard
              key={stage.id}
              agentId={agentId}
              stage={stage}
              index={index}
              busy={busy}
              onChanged={onSaved}
              onError={setError}
              onEdit={() => setEditingStage(stage.id)}
              onDelete={() => setPendingDeleteStage(stage)}
              canDelete={stages.length > 1}
            />
          ),
        )}
        {editingStage === "new" ? (
          <StageForm
            agentId={agentId}
            stage={null}
            bots={bots}
            onSaved={stageChanged}
            onCancel={() => setEditingStage(null)}
          />
        ) : (
          <Button size="sm" onClick={() => setEditingStage("new")}>
            <Plus /> Add stage
          </Button>
        )}
      </div>

      {stages.length > 1 && (
        <div className="space-y-2 pt-4">
          <div className="flex items-center justify-between gap-2">
            <div>
              <p className="text-sm font-semibold text-foreground">Hand-offs</p>
              <p className="text-xs text-muted-foreground">
                When a call ends and the first matching hand-off applies, the lead continues in the next stage as a new
                call record carrying the results. Leads that never connect move to the next stage in order unless a
                &quot;retries run out&quot; hand-off says otherwise.
              </p>
            </div>
            {editingTransition !== "new" && (
              <Button size="sm" onClick={() => setEditingTransition("new")}>
                <Plus /> Add hand-off
              </Button>
            )}
          </div>

          {transitions === null ? (
            <div className="h-12 bg-muted/50 rounded-lg animate-pulse" />
          ) : (
            transitions.length === 0 &&
            editingTransition !== "new" && <EmptySection label="No hand-offs yet — results stay in their own stage." />
          )}
          {(transitions ?? []).map((t, index) =>
            editingTransition === t.id ? (
              <TransitionForm
                key={t.id}
                agentId={agentId}
                transition={t}
                stages={stages}
                onSaved={() => {
                  setEditingTransition(null);
                  refreshTransitions();
                }}
                onCancel={() => setEditingTransition(null)}
              />
            ) : (
              <div key={t.id} className="flex items-center gap-3 rounded-lg border border-border px-3 py-2">
                <span className="text-xs font-mono text-muted-foreground w-5 shrink-0">{index + 1}</span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm text-foreground">
                    {t.from_name} <ArrowRight className="inline w-3.5 h-3.5 text-muted-foreground" /> {t.to_name}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {t.on === "completed" ? "When a call finishes" : "When retries run out"}
                    {t.checks.length > 0 && ` and ${describeChecks(t.checks, t.match)}`}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <Button variant="outline" size="sm" disabled={busy || index === 0} onClick={() => moveTransition(index, -1)} aria-label="Move up">
                    <ArrowUp />
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={busy || index === (transitions?.length ?? 0) - 1}
                    onClick={() => moveTransition(index, 1)}
                    aria-label="Move down"
                  >
                    <ArrowDown />
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setEditingTransition(t.id)}>
                    <Pencil /> Edit
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setPendingDeleteTransition(t)} aria-label="Remove hand-off">
                    <Trash2 />
                  </Button>
                </div>
              </div>
            ),
          )}
          {editingTransition === "new" && (
            <TransitionForm
              agentId={agentId}
              transition={null}
              stages={stages}
              onSaved={() => {
                setEditingTransition(null);
                refreshTransitions();
              }}
              onCancel={() => setEditingTransition(null)}
            />
          )}
        </div>
      )}

      <ConfirmDialog
        open={pendingDeleteStage !== null}
        onOpenChange={(o) => !o && setPendingDeleteStage(null)}
        title={`Remove stage "${pendingDeleteStage?.name ?? ""}"?`}
        description="Hand-offs into and out of it are removed too. Past calls keep their history."
        busy={busy}
        onConfirm={confirmDeleteStage}
      />
      <ConfirmDialog
        open={pendingDeleteTransition !== null}
        onOpenChange={(o) => !o && setPendingDeleteTransition(null)}
        title="Remove this hand-off?"
        description="Results from that stage will stay there."
        busy={busy}
        onConfirm={confirmDeleteTransition}
      />
    </SettingsSection>
  );
}
