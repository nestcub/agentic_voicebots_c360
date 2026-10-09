"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { ArrowRight, Network, Plus, Workflow } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
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
import { PageHeader } from "@/components/common/PageHeader";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { CHANNEL_ICONS, ChannelIconTile, DEFAULT_CHANNEL_COLOR } from "@/components/common/ChannelIcon";
import { ActiveBadge } from "@/components/StatusBadge";
import { listChannels, createChannel } from "@/lib/telehubApi";
import { cn } from "@/lib/utils";
import type { Channel } from "@/lib/types";

const COLOR_SWATCHES = [
  "#2563eb", // primary
  "#2fb6a8", // teal
  "#1ca674", // ok
  "#f0883e", // warn
  "#e2574c", // bad
  "#8b5cf6", // violet
];

interface NewChannelForm {
  name: string;
  description: string;
  icon: string;
  color: string;
}

const EMPTY_FORM: NewChannelForm = {
  name: "",
  description: "",
  icon: "folder",
  color: DEFAULT_CHANNEL_COLOR,
};

function NewChannelDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => Promise<unknown>;
}) {
  const [form, setForm] = useState<NewChannelForm>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(EMPTY_FORM);
    setFormError(null);
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      await createChannel({
        name: form.name.trim(),
        description: form.description.trim() || undefined,
        icon: form.icon || undefined,
        color: form.color || undefined,
      });
      await onCreated();
      toast.success(`Created channel "${form.name.trim()}"`);
      onOpenChange(false);
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Failed to create channel");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !submitting && onOpenChange(o)}>
      <DialogContent className="sm:max-w-lg">
        <form onSubmit={handleSubmit} className="space-y-5">
          <DialogHeader>
            <DialogTitle>New Channel</DialogTitle>
            <DialogDescription>Group related process agents, e.g. Sales or Service.</DialogDescription>
          </DialogHeader>

          {formError && <ErrorAlert message={formError} />}

          <div className="flex items-end gap-3">
            <ChannelIconTile icon={form.icon} color={form.color} />
            <div className="flex-1 space-y-1.5">
              <Label htmlFor="channel-name" className="text-xs text-muted-foreground">
                Name *
              </Label>
              <Input
                id="channel-name"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Sales"
                required
                autoFocus
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="channel-description" className="text-xs text-muted-foreground">
              Description
            </Label>
            <Textarea
              id="channel-description"
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              rows={2}
              placeholder="Short description of this channel"
            />
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Icon</Label>
            <div className="grid grid-cols-6 gap-2">
              {Object.entries(CHANNEL_ICONS).map(([key, Icon]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, icon: key }))}
                  aria-label={`Use ${key} icon`}
                  aria-pressed={form.icon === key}
                  className={cn(
                    "h-10 rounded-lg border flex items-center justify-center transition-colors",
                    form.icon === key
                      ? "border-primary bg-accent text-primary"
                      : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon className="w-4 h-4" />
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Color</Label>
            <div className="flex items-center gap-2">
              {COLOR_SWATCHES.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setForm((f) => ({ ...f, color: c }))}
                  className={cn(
                    "w-7 h-7 rounded-full border-2 transition-transform",
                    form.color === c ? "border-foreground scale-110" : "border-transparent",
                  )}
                  style={{ backgroundColor: c }}
                  aria-label={`Use color ${c}`}
                />
              ))}
              <input
                type="color"
                value={form.color}
                onChange={(e) => setForm((f) => ({ ...f, color: e.target.value }))}
                className="w-8 h-8 rounded border border-border bg-card cursor-pointer"
                aria-label="Custom color"
              />
            </div>
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting && <Spinner />}
              Create Channel
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default function ChannelsPage() {
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  function loadChannels() {
    setLoading(true);
    setError(null);
    return listChannels()
      .then((data) => {
        setChannels(data);
        setLoading(false);
      })
      .catch((e) => {
        setError(e instanceof Error ? e.message : "Failed to load channels");
        setLoading(false);
      });
  }

  useEffect(() => {
    loadChannels();
  }, []);

  const addButton = (
    <Button onClick={() => setFormOpen(true)}>
      <Plus /> Add Channel
    </Button>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Network}
        title="Channels"
        description="Organize process agents by channel"
        actions={addButton}
      />

      {error && (
        <ErrorAlert
          message={error}
          action={
            <Button variant="outline" size="sm" onClick={loadChannels}>
              Retry
            </Button>
          }
        />
      )}

      {loading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-40 rounded-xl" />
          ))}
        </div>
      )}

      {!loading && !error && channels.length === 0 && (
        <EmptyState
          icon={Network}
          title="No channels yet"
          description="Create your first channel to start building process agents."
          action={addButton}
        />
      )}

      {!loading && !error && channels.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {channels.map((d) => (
            <Link key={d.id} href={`/channels/${d.id}`} className="group">
              <Card
                className="h-full gap-0 p-5 border-l-4 transition-all group-hover:shadow-md group-hover:-translate-y-0.5"
                style={{ borderLeftColor: d.color || DEFAULT_CHANNEL_COLOR }}
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <ChannelIconTile icon={d.icon} color={d.color} />
                    <p className="text-base font-semibold text-foreground truncate">{d.name}</p>
                  </div>
                  <ActiveBadge active={d.is_active} />
                </div>
                <p className="text-sm text-muted-foreground line-clamp-2 min-h-10">
                  {d.description || "No description."}
                </p>
                <div className="flex items-center justify-between mt-4 pt-3 border-t border-border text-sm">
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <Workflow className="w-4 h-4" />
                    {d.process_agent_count} process agent{d.process_agent_count === 1 ? "" : "s"}
                  </span>
                  <ArrowRight className="w-4 h-4 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}

      <NewChannelDialog open={formOpen} onOpenChange={setFormOpen} onCreated={loadChannels} />
    </div>
  );
}
