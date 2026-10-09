"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  ChartColumn,
  ClipboardCheck,
  GitBranch,
  History,
  LayoutGrid,
  PhoneCall,
  Settings,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PageHeader } from "@/components/common/PageHeader";
import { EmptyState } from "@/components/common/EmptyState";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { ActiveBadge, ProcessStatusBadge, ToneBadge } from "@/components/StatusBadge";
import {
  getProcessAgent,
  getProcessAgentJourney,
  getProcessAgentBotJourneys,
  getProcessAgentExecutions,
  getProcessAgentQaResults,
  getProcessAgentStats,
  getProcessAgentAnalytics,
  updateProcessAgent,
  dispatchSingleCall,
  dispatchFollowUp,
} from "@/lib/telehubApi";
import type {
  ProcessAgentDetail,
  JourneyNode,
  JourneyEdge,
  BotJourney,
  Execution,
  QaResult,
  ProcessAgentStats,
  ProcessAgentAnalytics,
} from "@/lib/types";
import { TABS, type TabKey, errorMessage } from "@/components/process-agents/shared";
import { OverviewTab } from "@/components/process-agents/OverviewTab";
import { JourneyTab } from "@/components/process-agents/JourneyTab";
import { RunsTab } from "@/components/process-agents/RunsTab";
import { QaTab } from "@/components/process-agents/QaTab";
import { CallsTab } from "@/components/process-agents/CallsTab";
import { AnalyticsTab } from "@/components/process-agents/AnalyticsTab";
import { SettingsTab } from "@/components/process-agents/SettingsTab";

const TAB_ICONS: Record<TabKey, LucideIcon> = {
  overview: LayoutGrid,
  journey: GitBranch,
  runs: History,
  calls: PhoneCall,
  qa: ClipboardCheck,
  analytics: ChartColumn,
  settings: Settings,
};

export default function ProcessAgentDetailPage() {
  const params = useParams<{ id: string }>();
  const rawId = params?.id;
  const id = Number(Array.isArray(rawId) ? rawId[0] : rawId);
  const validId = Number.isFinite(id);

  const [agent, setAgent] = useState<ProcessAgentDetail | null>(null);
  const [agentLoading, setAgentLoading] = useState(true);
  const [agentError, setAgentError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const [tab, setTab] = useState<TabKey>("overview");

  // Journey tab state
  const [journeyData, setJourneyData] = useState<{ nodes: JourneyNode[]; edges: JourneyEdge[] } | null>(null);
  const [journeyLoading, setJourneyLoading] = useState(false);
  const [journeyError, setJourneyError] = useState<string | null>(null);
  const [journeyFetched, setJourneyFetched] = useState(false);

  // Bot Journeys tab state
  const [botJourneys, setBotJourneys] = useState<BotJourney[] | null>(null);
  const [botJourneysLoading, setBotJourneysLoading] = useState(false);
  const [botJourneysError, setBotJourneysError] = useState<string | null>(null);
  const [botJourneysFetched, setBotJourneysFetched] = useState(false);

  // Overview tab state
  const [stats, setStats] = useState<ProcessAgentStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [statsFetched, setStatsFetched] = useState(false);

  // Runs tab state
  const [executions, setExecutions] = useState<Execution[] | null>(null);
  const [executionsLoading, setExecutionsLoading] = useState(false);
  const [executionsError, setExecutionsError] = useState<string | null>(null);
  const [executionsFetched, setExecutionsFetched] = useState(false);

  // QA tab state
  const [qaResults, setQaResults] = useState<QaResult[] | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);
  const [qaFetched, setQaFetched] = useState(false);

  // Analytics tab state
  const [analyticsData, setAnalyticsData] = useState<ProcessAgentAnalytics | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [analyticsError, setAnalyticsError] = useState<string | null>(null);
  const [analyticsFetched, setAnalyticsFetched] = useState(false);

  // Settings tab: active toggle
  const [togglingActive, setTogglingActive] = useState(false);
  const [toggleError, setToggleError] = useState<string | null>(null);

  const [relaunching, setRelaunching] = useState(false);
  const [relaunchError, setRelaunchError] = useState<string | null>(null);
  const [relaunchResult, setRelaunchResult] = useState<string | null>(null);

  const loadAgent = useCallback(() => {
    if (!validId) {
      setAgentLoading(false);
      setNotFound(true);
      return;
    }
    setAgentLoading(true);
    setAgentError(null);
    setNotFound(false);
    getProcessAgent(id)
      .then((data) => {
        setAgent(data);
        setAgentLoading(false);
      })
      .catch((e: unknown) => {
        const message = errorMessage(e, "Failed to load process agent");
        if (message.includes("404")) {
          setNotFound(true);
        } else {
          setAgentError(message);
        }
        setAgentLoading(false);
      });
  }, [id, validId]);

  useEffect(() => {
    loadAgent();
  }, [loadAgent]);

  // Lazy fetch: Overview stats
  useEffect(() => {
    if (!validId || tab !== "overview" || statsFetched) return;
    let cancelled = false;
    setStatsLoading(true);
    setStatsError(null);
    getProcessAgentStats(id)
      .then((data) => {
        if (cancelled) return;
        setStats(data);
        setStatsFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setStatsError(errorMessage(e, "Failed to load stats"));
        setStatsFetched(true);
      })
      .finally(() => {
        if (!cancelled) setStatsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, statsFetched, id]);

  // Lazy fetch: Journey — also feeds Settings (Voice/QA sections read the
  // Communication/QA NodeInstance configs off this same data) and Runs (needs
  // communication_type to gate the single-source dispatch button).
  useEffect(() => {
    if (!validId || (tab !== "journey" && tab !== "settings" && tab !== "runs") || journeyFetched) return;
    let cancelled = false;
    setJourneyLoading(true);
    setJourneyError(null);
    getProcessAgentJourney(id)
      .then((data) => {
        if (cancelled) return;
        setJourneyData(data);
        setJourneyFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setJourneyError(errorMessage(e, "Failed to load journey"));
        setJourneyFetched(true);
      })
      .finally(() => {
        if (!cancelled) setJourneyLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, journeyFetched, id]);

  // Lazy fetch: Bot Journeys — feeds Runs (bot picker for the single-source
  // dispatch button) and QA (bot picker for "Dispatch Follow-up").
  useEffect(() => {
    if (!validId || (tab !== "runs" && tab !== "qa") || botJourneysFetched) return;
    let cancelled = false;
    setBotJourneysLoading(true);
    setBotJourneysError(null);
    getProcessAgentBotJourneys(id)
      .then((data) => {
        if (cancelled) return;
        setBotJourneys(data);
        setBotJourneysFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setBotJourneysError(errorMessage(e, "Failed to load bot journeys"));
        setBotJourneysFetched(true);
      })
      .finally(() => {
        if (!cancelled) setBotJourneysLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, botJourneysFetched, id]);

  // Lazy fetch: Runs
  useEffect(() => {
    if (!validId || tab !== "runs" || executionsFetched) return;
    let cancelled = false;
    setExecutionsLoading(true);
    setExecutionsError(null);
    getProcessAgentExecutions(id)
      .then((data) => {
        if (cancelled) return;
        setExecutions(data);
        setExecutionsFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setExecutionsError(errorMessage(e, "Failed to load executions"));
        setExecutionsFetched(true);
      })
      .finally(() => {
        if (!cancelled) setExecutionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, executionsFetched, id]);

  // Lazy fetch: QA
  useEffect(() => {
    if (!validId || tab !== "qa" || qaFetched) return;
    let cancelled = false;
    setQaLoading(true);
    setQaError(null);
    getProcessAgentQaResults(id)
      .then((data) => {
        if (cancelled) return;
        setQaResults(data);
        setQaFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setQaError(errorMessage(e, "Failed to load QA results"));
        setQaFetched(true);
      })
      .finally(() => {
        if (!cancelled) setQaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, qaFetched, id]);

  // Lazy fetch: Analytics
  useEffect(() => {
    if (!validId || tab !== "analytics" || analyticsFetched) return;
    let cancelled = false;
    setAnalyticsLoading(true);
    setAnalyticsError(null);
    getProcessAgentAnalytics(id)
      .then((data) => {
        if (cancelled) return;
        setAnalyticsData(data);
        setAnalyticsFetched(true);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setAnalyticsError(errorMessage(e, "Failed to load analytics"));
        setAnalyticsFetched(true);
      })
      .finally(() => {
        if (!cancelled) setAnalyticsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [validId, tab, analyticsFetched, id]);

  // Settings tab edits: QA-config lives on a NodeInstance inside journeyData,
  // not on `agent` — force the journey effect above to refetch by flipping
  // journeyFetched back to false (still gated on tab === "settings").
  const refreshJourney = useCallback(() => {
    setJourneyFetched(false);
  }, []);

  async function handleToggleActive() {
    if (!agent) return;
    setTogglingActive(true);
    setToggleError(null);
    try {
      await updateProcessAgent(agent.id, { is_active: !agent.is_active });
      loadAgent();
    } catch (e) {
      setToggleError(errorMessage(e, "Failed to update status"));
    } finally {
      setTogglingActive(false);
    }
  }

  async function handleDispatchSingleCall(params: Record<string, string>, botJourneyId?: number) {
    if (!agent || relaunching) return;
    setRelaunching(true);
    setRelaunchError(null);
    setRelaunchResult(null);
    try {
      const result = await dispatchSingleCall(agent.id, params, botJourneyId);
      if (result.success) {
        setRelaunchResult(`Call dispatched (status ${result.status_code}).`);
      } else {
        setRelaunchError(result.error || `Dispatch failed (status ${result.status_code}).`);
      }
    } catch (e) {
      setRelaunchError(errorMessage(e, "Failed to dispatch call"));
    } finally {
      setRelaunching(false);
    }
  }

  // QA tab's "Dispatch Follow-up" — returned to the caller rather than kept in
  // page-level state, since each QA row manages its own bot picker/result UI.
  async function handleDispatchFollowUp(executionId: number, botJourneyId: number) {
    if (!agent) throw new Error("Agent not loaded");
    return dispatchFollowUp(agent.id, { execution_id: executionId, bot_journey_id: botJourneyId });
  }

  if (!validId || notFound) {
    return (
      <EmptyState
        icon={Workflow}
        title="Agent not found"
        description="This agent doesn't exist or may have been removed."
        action={
          <Button variant="outline" asChild>
            <Link href="/channels">
              <ArrowLeft /> Back to Channels
            </Link>
          </Button>
        }
        className="py-24"
      />
    );
  }

  if (agentLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-48" />
        <div className="flex items-center gap-3">
          <Skeleton className="h-11 w-11 rounded-xl" />
          <Skeleton className="h-6 w-64" />
        </div>
        <Skeleton className="h-9 w-full max-w-xl" />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (agentError || !agent) {
    return (
      <ErrorAlert
        message={agentError ?? "Failed to load process agent."}
        action={
          <Button variant="outline" size="sm" onClick={loadAgent}>
            Retry
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <PageHeader
        breadcrumbs={[
          { label: "Channels", href: "/channels" },
          { label: agent.channel_name, href: `/channels/${agent.channel}` },
          { label: agent.name },
        ]}
        icon={Workflow}
        title={agent.name}
        badges={
          <>
            <ProcessStatusBadge status={agent.status} />
            <ActiveBadge active={agent.is_active} />
            <ToneBadge tone="muted" className="normal-case">
              v{agent.version}
            </ToneBadge>
          </>
        }
        description={agent.description || undefined}
      />

      <Tabs value={tab} onValueChange={(v) => setTab(v as TabKey)}>
        <div className="overflow-x-auto pb-1">
          <TabsList className="h-10">
            {TABS.map((t) => {
              const Icon = TAB_ICONS[t.key];
              return (
                <TabsTrigger key={t.key} value={t.key} className="px-3">
                  <Icon />
                  {t.label}
                </TabsTrigger>
              );
            })}
          </TabsList>
        </div>
      </Tabs>

      {/* Tab content */}
      {tab === "overview" && (
        <OverviewTab agent={agent} stats={stats} statsLoading={statsLoading} statsError={statsError} />
      )}
      {tab === "journey" && (
        <JourneyTab
          journeyData={journeyData}
          journeyLoading={journeyLoading}
          journeyError={journeyError}
        />
      )}
      {tab === "runs" && (
        <RunsTab
          executions={executions}
          loading={executionsLoading}
          error={executionsError}
          agent={agent}
          journeyData={journeyData}
          journeyLoading={journeyLoading}
          onDispatchSingleSource={handleDispatchSingleCall}
          dispatching={relaunching}
          dispatchError={relaunchError}
          dispatchResult={relaunchResult}
          botJourneys={botJourneys}
        />
      )}
      {tab === "calls" && <CallsTab agent={agent} />}
      {tab === "qa" && (
        <QaTab
          qaResults={qaResults}
          loading={qaLoading}
          error={qaError}
          botJourneys={botJourneys}
          onDispatchFollowUp={handleDispatchFollowUp}
        />
      )}
      {tab === "analytics" && (
        <AnalyticsTab agent={agent} data={analyticsData} loading={analyticsLoading} error={analyticsError} />
      )}
      {tab === "settings" && (
        <SettingsTab
          agent={agent}
          journeyData={journeyData}
          journeyLoading={journeyLoading}
          onToggleActive={handleToggleActive}
          toggling={togglingActive}
          toggleError={toggleError}
          onAgentChanged={loadAgent}
          onJourneyChanged={refreshJourney}
        />
      )}
    </div>
  );
}
