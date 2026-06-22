"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

const INTEL_URL = process.env.NEXT_PUBLIC_INTEL_API_URL ?? "http://localhost:8001";
const INTEL_KEY = process.env.NEXT_PUBLIC_INTEL_API_KEY ?? "";

const apiHeaders = () => ({
  "x-api-key": INTEL_KEY,
  "Content-Type": "application/json",
});

// ── Types ──────────────────────────────────────────────────────────────────────

type ClarifyQuestion = {
  id: string;
  question: string;
  options: string[] | null;
  why?: string;
};

type Answer = {
  question: string;
  answer: string;
};

// ── Step indicator ─────────────────────────────────────────────────────────────

const STEPS = ["Use Case", "Recordings", "Questions", "Notes", "Generating"];

function StepIndicator({ current }: { current: number }) {
  return (
    <div className="flex items-center gap-0 mb-8">
      {STEPS.map((label, idx) => {
        const stepNum = idx + 1;
        const isCompleted = stepNum < current;
        const isCurrent = stepNum === current;
        const isLast = idx === STEPS.length - 1;

        return (
          <div key={label} className="flex items-center flex-1 last:flex-none">
            <div className="flex flex-col items-center">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
                  isCompleted
                    ? "bg-blue-600 text-white"
                    : isCurrent
                    ? "bg-blue-600 text-white ring-4 ring-blue-100"
                    : "bg-gray-100 text-gray-400"
                }`}
              >
                {isCompleted ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  stepNum
                )}
              </div>
              <span
                className={`mt-1.5 text-xs font-medium whitespace-nowrap ${
                  isCurrent ? "text-blue-600" : isCompleted ? "text-gray-600" : "text-gray-400"
                }`}
              >
                {label}
              </span>
            </div>
            {!isLast && (
              <div
                className={`flex-1 h-0.5 mx-2 mb-5 transition-colors ${
                  isCompleted ? "bg-blue-600" : "bg-gray-200"
                }`}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function WizardPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const clientId = searchParams.get("client_id") ?? "";

  const [step, setStep] = useState(1);

  // Step 1
  const [useCase, setUseCase] = useState("");
  const [model, setModel] = useState<"sonnet" | "gpt-4.1" | "gpt-5.4">("gpt-5.4");

  // Step 2 – recordings status + copy from existing bot
  const [transcriptCount, setTranscriptCount] = useState<number | null>(null);
  const [transcriptLoading, setTranscriptLoading] = useState(false);
  const [sourceClientId, setSourceClientId] = useState<string>("");
  const [existingBots, setExistingBots] = useState<{ client_id: string; bot_name: string; status: string }[]>([]);
  const [loadingBots, setLoadingBots] = useState(false);

  // Step 3
  const [clarifyLoading, setClarifyLoading] = useState(false);
  const [clarifyError, setClarifyError] = useState("");
  const [questions, setQuestions] = useState<ClarifyQuestion[]>([]);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const clarifyCalledRef = useRef(false);

  // Step 4 – additional notes
  const [notes, setNotes] = useState("");

  // Step 5
  const [generateError, setGenerateError] = useState("");
  const [generating, setGenerating] = useState(false);
  const generateCalledRef = useRef(false);

  // ── Step 2: fetch transcripts + existing bots; re-check on tab focus return ──

  async function fetchTranscriptCount() {
    if (!clientId) return;
    setTranscriptLoading(true);
    try {
      const r = await fetch(`${INTEL_URL}/transcripts?client_id=${encodeURIComponent(clientId)}`, { headers: apiHeaders() });
      if (r.ok) {
        const data = await r.json();
        setTranscriptCount(Array.isArray(data) ? data.length : 0);
      }
    } catch { /* non-fatal */ } finally {
      setTranscriptLoading(false);
    }
  }

  useEffect(() => {
    if (step !== 2) return;
    // Initial fetch
    fetchTranscriptCount();
    setLoadingBots(true);
    fetch(`${INTEL_URL}/bots`, { headers: apiHeaders() })
      .then(r => r.json())
      .then(data => {
        setExistingBots(
          (data.bots ?? []).filter((b: { client_id: string }) => b.client_id !== clientId)
        );
      })
      .finally(() => setLoadingBots(false));

    // Re-fetch transcript count whenever user returns to this tab
    function onVisibility() {
      if (document.visibilityState === "visible") fetchTranscriptCount();
    }
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, clientId]);

  // ── Step 3: call /clarify on enter ──

  useEffect(() => {
    if (step !== 3 || clarifyCalledRef.current) return;
    clarifyCalledRef.current = true;
    callClarify();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  async function callClarify() {
    setClarifyLoading(true);
    setClarifyError("");
    try {
      const res = await fetch(`${INTEL_URL}/clarify`, {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({ client_id: clientId, use_case: useCase, model, ...(sourceClientId ? { source_client_id: sourceClientId } : {}) }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      const data: { questions: ClarifyQuestion[] } = await res.json();
      setQuestions(data.questions ?? []);
    } catch (err: unknown) {
      setClarifyError(err instanceof Error ? err.message : "Failed to load questions.");
    } finally {
      setClarifyLoading(false);
    }
  }

  function handleRetryClarify() {
    clarifyCalledRef.current = false;
    setQuestions([]);
    callClarify();
    clarifyCalledRef.current = true;
  }

  // ── Step 5: call /generate on enter ──

  useEffect(() => {
    if (step !== 5 || generateCalledRef.current) return;
    generateCalledRef.current = true;
    callGenerate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  async function callGenerate() {
    setGenerating(true);
    setGenerateError("");
    const answerList: Answer[] = questions.map((q) => ({
      question: q.question,
      answer: answers[q.id] ?? "",
    }));
    try {
      const res = await fetch(`${INTEL_URL}/generate`, {
        method: "POST",
        headers: apiHeaders(),
        body: JSON.stringify({
          client_id: clientId,
          use_case: useCase,
          answers: answerList,
          model,
          ...(sourceClientId ? { source_client_id: sourceClientId } : {}),
          ...(notes.trim() ? { notes } : {}),
        }),
      });
      if (!res.ok) throw new Error(`Server error ${res.status}`);
      await res.json();
      router.push(`/intelligence/bot?client_id=${encodeURIComponent(clientId)}&tab=build`);
    } catch (err: unknown) {
      setGenerateError(err instanceof Error ? err.message : "Generation failed.");
      setGenerating(false);
    }
  }

  function handleRetryGenerate() {
    generateCalledRef.current = false;
    callGenerate();
    generateCalledRef.current = true;
  }

  // ── Render ────────────────────────────────────────────────────────────────────

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-lg font-semibold text-gray-800">New Bot Wizard</h1>
        <p className="text-xs text-gray-400 mt-0.5">
          {clientId ? `Client: ${clientId}` : "No client_id in URL — results may not save correctly."}
        </p>
      </div>

      <StepIndicator current={step} />

      {/* ── Step 1: Use Case ── */}
      {step === 1 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-gray-800">Describe your bot</h2>
            <p className="text-sm text-gray-500 mt-1">
              What should this bot do? Be as specific as you like — language, industry, goal.
            </p>
          </div>
          <textarea
            className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 min-h-[120px]"
            placeholder='e.g. "Outbound auto-loan follow-up in Hindi — remind customers of upcoming EMI, handle objections, escalate to agent if needed."'
            value={useCase}
            onChange={(e) => setUseCase(e.target.value)}
          />

          {/* Generation model — pick which LLM writes the 12-section prompt */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Generation model</label>
            <div className="flex items-center gap-2">
              {([
                { key: "sonnet", label: "Sonnet 4.6" },
                { key: "gpt-4.1", label: "GPT-4.1" },
                { key: "gpt-5.4", label: "GPT-5.4" },
              ] as const).map((m) => (
                <button
                  key={m.key}
                  onClick={() => setModel(m.key)}
                  className={`px-3 py-1.5 rounded-lg text-sm border transition-colors ${
                    model === m.key
                      ? "bg-blue-600 text-white border-blue-600"
                      : "bg-white text-gray-600 border-gray-200 hover:border-gray-400"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-gray-400">This model writes the clarifying questions and the 12-section prompt. Compare outputs by creating one bot per model.</p>
          </div>

          <div className="flex justify-end">
            <button
              onClick={() => setStep(2)}
              disabled={!useCase.trim()}
              className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}

      {/* ── Step 2: Recordings ── */}
      {step === 2 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-gray-800">
              Upload call recordings{" "}
              <span className="text-gray-400 font-normal text-sm">(optional)</span>
            </h2>
            <p className="text-sm text-gray-500 mt-1">
              Uploading real call recordings lets the AI learn from your actual conversations and
              improve the bot's quality significantly.
            </p>
          </div>

          <div className="p-4 bg-gray-50 border border-gray-200 rounded-lg space-y-3">
            <div className="flex items-center justify-between">
              <p className="text-sm text-gray-600 font-medium">Transcribe recordings</p>
              {/* Live recording status */}
              {transcriptLoading && (
                <span className="text-xs text-gray-400 flex items-center gap-1">
                  <span className="w-3 h-3 border-2 border-gray-300 border-t-transparent rounded-full animate-spin" />
                  Checking…
                </span>
              )}
              {!transcriptLoading && transcriptCount !== null && transcriptCount > 0 && (
                <span className="text-xs font-medium text-green-700 bg-green-50 border border-green-200 px-2 py-0.5 rounded-full flex items-center gap-1">
                  <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                  {transcriptCount} recording{transcriptCount === 1 ? "" : "s"} ready
                </span>
              )}
              {!transcriptLoading && transcriptCount === 0 && (
                <span className="text-xs text-gray-400">No recordings yet</span>
              )}
            </div>
            <p className="text-sm text-gray-500">
              Use the Transcribe page to upload WAV / MP3 / M4A files. Come back here after — the
              count above updates automatically when you return to this tab.
            </p>
            <div className="flex items-center gap-3">
              <a
                href={`/intelligence/transcribe${clientId ? `?client_id=${encodeURIComponent(clientId)}` : ""}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium border border-gray-300 rounded-lg hover:bg-gray-100 transition-colors text-gray-700"
              >
                Go to Transcribe page
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                </svg>
              </a>
              {transcriptCount !== null && transcriptCount > 0 && (
                <button
                  onClick={fetchTranscriptCount}
                  className="text-xs text-blue-600 hover:underline"
                >
                  Refresh
                </button>
              )}
            </div>
          </div>

          <div className="mt-4 border-t border-gray-100 pt-4">
            <p className="text-sm font-medium text-gray-700 mb-2">
              Or copy insights from an existing bot:
            </p>
            {loadingBots ? (
              <p className="text-xs text-gray-400">Loading bots…</p>
            ) : existingBots.length === 0 ? (
              <p className="text-xs text-gray-400">No other bots with recordings found.</p>
            ) : (
              <select
                value={sourceClientId}
                onChange={e => setSourceClientId(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— select a bot —</option>
                {existingBots
                  .filter(b => b.status === "built" || b.status === "transcribed")
                  .map(b => (
                    <option key={b.client_id} value={b.client_id}>
                      {b.bot_name || b.client_id} ({b.status})
                    </option>
                  ))}
              </select>
            )}
            {sourceClientId && (
              <p className="text-xs text-green-600 mt-1.5">
                ✓ Insights from this bot will be used to guide generation.
              </p>
            )}
          </div>

          <div className="flex flex-col sm:flex-row gap-3 pt-2">
            {transcriptCount !== null && transcriptCount > 0 ? (
              <button
                onClick={() => setStep(3)}
                className="flex-1 px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
              >
                Continue with {transcriptCount} recording{transcriptCount === 1 ? "" : "s"}
              </button>
            ) : (
              <button
                onClick={() => setStep(3)}
                className="flex-1 px-5 py-2.5 text-gray-600 text-sm font-medium border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Skip — generate without recordings
              </button>
            )}
          </div>

          <div className="flex justify-start">
            <button
              onClick={() => setStep(1)}
              className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
            >
              Back
            </button>
          </div>
        </div>
      )}

      {/* ── Step 3: Clarifying Questions ── */}
      {step === 3 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-gray-800">A few quick questions</h2>
            <p className="text-sm text-gray-500 mt-1">
              These help the AI tailor the bot to your exact situation.
            </p>
          </div>

          {clarifyLoading && (
            <div className="flex items-center justify-center py-12 gap-3 text-gray-400">
              <svg
                className="w-5 h-5 animate-spin text-blue-500"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
              </svg>
              <span className="text-sm">Generating questions…</span>
            </div>
          )}

          {!clarifyLoading && clarifyError && (
            <div className="p-4 bg-red-50 border border-red-200 rounded-lg space-y-3">
              <p className="text-sm text-red-600">{clarifyError}</p>
              <button
                onClick={handleRetryClarify}
                className="px-4 py-2 text-sm font-medium bg-white border border-red-300 text-red-600 rounded-lg hover:bg-red-50 transition-colors"
              >
                Retry
              </button>
            </div>
          )}

          {!clarifyLoading && !clarifyError && questions.length > 0 && (
            <div className="space-y-4">
              {questions.map((q) => (
                <div
                  key={q.id}
                  className="p-4 border border-gray-200 rounded-lg space-y-3 bg-gray-50"
                >
                  <div>
                    <p className="text-sm font-medium text-gray-800">{q.question}</p>
                    {q.why && (
                      <p className="text-xs text-gray-400 mt-0.5 italic">{q.why}</p>
                    )}
                  </div>

                  {q.options && q.options.length > 0 ? (
                    <div className="space-y-2">
                      {q.options.map((opt) => (
                        <label
                          key={opt}
                          className="flex items-center gap-2.5 cursor-pointer group"
                        >
                          <input
                            type="radio"
                            name={`q-${q.id}`}
                            value={opt}
                            checked={answers[q.id] === opt}
                            onChange={() =>
                              setAnswers((prev) => ({ ...prev, [q.id]: opt }))
                            }
                            className="w-4 h-4 accent-blue-600"
                          />
                          <span className="text-sm text-gray-700 group-hover:text-gray-900">
                            {opt}
                          </span>
                        </label>
                      ))}
                      {/* Other / write a note */}
                      <label className="flex items-start gap-2.5 cursor-pointer group">
                        <input
                          type="radio"
                          name={`q-${q.id}`}
                          value="__other__"
                          checked={answers[q.id] !== undefined && !q.options.includes(answers[q.id])}
                          onChange={() =>
                            setAnswers((prev) => ({ ...prev, [q.id]: "" }))
                          }
                          className="w-4 h-4 accent-blue-600 mt-0.5"
                        />
                        <span className="text-sm text-gray-500 group-hover:text-gray-700">
                          Other / write a note…
                        </span>
                      </label>
                      {answers[q.id] !== undefined && !q.options.includes(answers[q.id]) && (
                        <input
                          type="text"
                          value={answers[q.id] ?? ""}
                          onChange={(e) =>
                            setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                          }
                          placeholder="Type your answer…"
                          autoFocus
                          className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400 ml-6"
                        />
                      )}
                    </div>
                  ) : (
                    <input
                      type="text"
                      value={answers[q.id] ?? ""}
                      onChange={(e) =>
                        setAnswers((prev) => ({ ...prev, [q.id]: e.target.value }))
                      }
                      placeholder="Your answer…"
                      className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
                    />
                  )}
                </div>
              ))}
            </div>
          )}

          {!clarifyLoading && !clarifyError && questions.length === 0 && !clarifyLoading && (
            <p className="text-sm text-gray-400 text-center py-8">No questions returned — you can proceed.</p>
          )}

          <div className="flex items-center justify-between pt-2">
            <button
              onClick={() => setStep(2)}
              className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
            >
              Back
            </button>
            <button
              onClick={() => setStep(4)}
              disabled={clarifyLoading}
              className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 transition-colors"
            >
              Generate Bot
            </button>
          </div>
        </div>
      )}

      {/* ── Step 4: Additional Notes ── */}
      {step === 4 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5 shadow-sm">
          <div>
            <h2 className="text-base font-semibold text-gray-800">Anything else to add?</h2>
            <p className="text-sm text-gray-500 mt-1">
              Add any extra context, constraints, or instructions for the LLM before it generates
              your bot. This is optional — leave blank to skip.
            </p>
          </div>
          <textarea
            className="w-full rounded-lg border border-gray-200 text-sm text-gray-800 placeholder-gray-400 p-3 resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 min-h-[140px]"
            placeholder={`e.g. "The bot must never put callers on hold. Always use formal Hindi. The CRM variable for lead ID is @lead_id."`}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className="flex items-center justify-between pt-1">
            <button
              onClick={() => setStep(3)}
              className="text-sm text-gray-400 hover:text-gray-600 transition-colors"
            >
              Back
            </button>
            <button
              onClick={() => setStep(5)}
              className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
            >
              {notes.trim() ? "Generate Bot" : "Skip & Generate"}
            </button>
          </div>
        </div>
      )}

      {/* ── Step 5: Generating ── */}
      {step === 5 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 shadow-sm">
          {generating && !generateError && (
            <div className="flex flex-col items-center justify-center py-16 space-y-5 text-center">
              <svg
                className="w-10 h-10 animate-spin text-blue-500"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                />
              </svg>
              <div>
                <p className="text-base font-semibold text-gray-800">Building your bot…</p>
                <p className="text-sm text-gray-400 mt-1">
                  Generating system prompt, workflow, and knowledge base. This takes 15–30 seconds.
                </p>
              </div>
            </div>
          )}

          {generateError && (
            <div className="space-y-5">
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-sm font-medium text-red-700 mb-1">Generation failed</p>
                <p className="text-sm text-red-600">{generateError}</p>
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={handleRetryGenerate}
                  className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
                >
                  Retry
                </button>
                <button
                  onClick={() => { setStep(3); generateCalledRef.current = false; }}
                  className="px-4 py-2 text-sm text-gray-500 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  Back to Questions
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
