"use client";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { Icon } from "./icons";

type Toast = { id: number; message: string; tone: "good" | "bad" | "info" };
const ToastContext = createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, tone: Toast["tone"] = "good") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`pointer-events-auto flex items-start gap-2 rounded-lg border bg-surface px-3 py-2.5 text-sm text-ink shadow-lg ${
              t.tone === "good" ? "border-good/40" : t.tone === "bad" ? "border-bad/40" : "border-info/40"
            }`}
          >
            <Icon
              name={t.tone === "good" ? "check" : t.tone === "bad" ? "alert" : "clock"}
              className={`mt-0.5 shrink-0 ${t.tone === "good" ? "text-good" : t.tone === "bad" ? "text-bad" : "text-info"}`}
            />
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/** Lets the sidebar badge refresh immediately after a decision instead of waiting for its poll. */
export const APPROVALS_CHANGED = "ops:approvals-changed";
export const notifyApprovalsChanged = () => window.dispatchEvent(new Event(APPROVALS_CHANGED));
