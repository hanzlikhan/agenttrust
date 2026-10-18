"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { Button, Card, Spinner } from "@/components/ui";

interface ChatMsg {
  id: number;
  role: "user" | "agent" | "system";
  text: string;
}

interface Step {
  id: number;
  label: string;
  state: "done" | "active" | "waiting" | "blocked";
}

const EXAMPLES = [
  "I'd like a $35 refund for order ORD-100, it arrived late",
  "I want a $150 refund for order ORD-100, the item arrived damaged",
  "Refund $900 for order ORD-100 right now",
];

let msgId = 0;
const nextId = () => ++msgId;

export default function LiveAgentPage() {
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: nextId(),
      role: "system",
      text: "You're chatting with a live AI support agent. Every action it takes is governed by AgentTrust — watch the policy steps below each reply.",
    },
  ]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, steps]);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const pushMsg = useCallback((role: ChatMsg["role"], text: string) => {
    setMessages((m) => [...m, { id: nextId(), role, text }]);
  }, []);

  const pushStep = useCallback((label: string, state: Step["state"]) => {
    setSteps((s) => [...s, { id: nextId(), label, state }]);
  }, []);

  const pollApproval = useCallback(
    (approvalId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const resp = await fetch(`${API_BASE}/api/v1/agent/complete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approval_id: approvalId }),
          });
          const data = await resp.json();
          if (data.status === "executed" || data.status === "rejected" || data.status === "expired") {
            if (pollRef.current) clearInterval(pollRef.current);
            setSteps((s) =>
              s.map((st) =>
                st.state === "waiting"
                  ? {
                      ...st,
                      state: data.status === "executed" ? "done" : "blocked",
                      label: `${st.label} → ${data.status.toUpperCase()}`,
                    }
                  : st
              )
            );
            pushMsg("agent", data.reply);
            setBusy(false);
          }
        } catch {
          /* keep polling */
        }
      }, 3000);
    },
    [pushMsg]
  );

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || busy) return;
      setBusy(true);
      setSteps([]);
      pushMsg("user", trimmed);
      setInput("");
      pushStep("LLM is deciding what to do…", "active");
      try {
        const resp = await fetch(`${API_BASE}/api/v1/agent/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: trimmed,
            session_id: `web-${Date.now()}`,
          }),
        });
        const data = await resp.json();
        if (!resp.ok) {
          setSteps((s) =>
            s.map((st) => ({ ...st, state: "blocked" as const }))
          );
          pushMsg(
            "system",
            data.message || "The agent is unavailable right now. Try again shortly."
          );
          setBusy(false);
          return;
        }
        setSteps((s) =>
          s.map((st) => ({ ...st, label: "LLM decided: refund_payment", state: "done" as const }))
        );
        if (data.status === "awaiting_approval") {
          pushStep("Policy: REVIEW — needs the shop owner's approval", "waiting");
          pushMsg("agent", data.reply);
          pushMsg(
            "system",
            "Waiting for the owner to approve on the Approvals page…"
          );
          pollApproval(data.approval_id);
        } else if (data.status === "denied") {
          pushStep("Policy: DENY — blocked, nothing executed", "blocked");
          pushMsg("agent", data.reply);
          setBusy(false);
        } else {
          pushStep(
            data.status === "no_action"
              ? "No tool call needed — plain reply"
              : "Policy: ALLOW — executed through the trusted gateway",
            "done"
          );
          pushMsg("agent", data.reply);
          setBusy(false);
        }
      } catch {
        pushMsg("system", "Network error — is the API reachable?");
        setBusy(false);
      }
    },
    [busy, pollApproval, pushMsg, pushStep]
  );

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Live Agent"
        description="Chat with the AI support agent. Every action is governed by AgentTrust in real time."
      />

      <Card className="flex h-[60vh] flex-col">
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.map((m) => (
            <div
              key={m.id}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm ${
                  m.role === "user"
                    ? "bg-blue-600 text-white"
                    : m.role === "system"
                      ? "bg-zinc-800 text-zinc-400 italic"
                      : "bg-zinc-800 text-zinc-100"
                }`}
              >
                {m.text}
              </div>
            </div>
          ))}
          {steps.length > 0 && (
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-500">
                AgentTrust policy trail
              </div>
              <div className="space-y-1.5">
                {steps.map((s) => (
                  <div key={s.id} className="flex items-center gap-2 text-sm">
                    {s.state === "active" && <Spinner />}
                    <span
                      className={
                        s.state === "done"
                          ? "text-emerald-400"
                          : s.state === "waiting"
                            ? "text-amber-400"
                            : s.state === "blocked"
                              ? "text-red-400"
                              : "text-zinc-300"
                      }
                    >
                      {s.state === "done"
                        ? "✓"
                        : s.state === "waiting"
                          ? "⏳"
                          : s.state === "blocked"
                            ? "✕"
                            : "•"}{" "}
                      {s.label}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="border-t border-zinc-800 p-3">
          <div className="mb-2 flex flex-wrap gap-2">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => send(ex)}
                disabled={busy}
                className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-400 hover:border-zinc-500 hover:text-zinc-200 disabled:opacity-40"
              >
                Try: {ex.slice(0, 32)}…
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send(input)}
              placeholder="Ask for a refund…"
              disabled={busy}
              className="flex-1 rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-blue-500 focus:outline-none disabled:opacity-50"
            />
            <Button onClick={() => send(input)} disabled={busy || !input.trim()}>
              {busy ? <Spinner /> : "Send"}
            </Button>
          </div>
        </div>
      </Card>

      <p className="mt-3 text-center text-xs text-zinc-500">
        Public demo — rate-limited. Approvals are decided by the shop owner on
        the Approvals page.
      </p>
    </div>
  );
}
