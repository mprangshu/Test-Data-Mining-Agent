import React, { useEffect, useRef } from "react";

// Left rail: chat-style transcript of the session. User bubbles (right) = what the user gave the
// agent; agent bubbles (left) = a human summary of what the agent did, driven by the NDJSON stream.
// Dividers mark each generate-more round. Auto-scrolls to the newest message.
export default function ChatPanel({ messages = [] }) {
  const endRef = useRef(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  return (
    <div className="flex h-full flex-col">
      <h2 className="shrink-0 px-3 pt-3 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        Activity
      </h2>
      <div className="flex-1 space-y-2 overflow-y-auto px-3 pb-4">
        {messages.length === 0 && (
          <p className="mt-6 text-center text-xs text-slate-400">
            Your uploads and the agent's steps will appear here as a conversation.
          </p>
        )}
        {messages.map((m) =>
          m.role === "divider" ? (
            <div key={m.id} className="flex items-center gap-2 py-2 text-[11px] text-slate-400">
              <span className="h-px flex-1 bg-slate-200" />
              {m.text}
              <span className="h-px flex-1 bg-slate-200" />
            </div>
          ) : (
            <Bubble key={m.id} role={m.role} text={m.text} />
          )
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}

function Bubble({ role, text }) {
  const user = role === "user";
  return (
    <div className={`flex ${user ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[88%] whitespace-pre-line rounded-2xl px-3 py-1.5 text-xs leading-snug ${
          user
            ? "rounded-br-sm bg-accent text-white"
            : "rounded-bl-sm border border-slate-200 bg-slate-50 text-slate-700"
        }`}
      >
        {text}
      </div>
    </div>
  );
}
