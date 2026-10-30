const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 2 });

export const money = (minor: number | undefined | null, currency = "INR") =>
  minor == null ? "—" : currency === "INR" ? inr.format(minor / 100) : `${(minor / 100).toFixed(2)} ${currency}`;

export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—";

export const day = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" }) : "—";

export const time = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "";

export const ACTION_TITLE: Record<string, string> = { refund: "Refund", send_reply: "Customer reply", escalate_ticket: "Escalate ticket" };
export const actionTitle = (type: string) => ACTION_TITLE[type] ?? type.replaceAll("_", " ");

export const label = (value: string) => value.replaceAll("_", " ");

/** "5 min ago", "in 23 h", "2 d ago". */
export function relative(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "—";
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff) / 1000;
  const [value, unit] =
    abs < 60 ? [Math.round(abs), "s"] : abs < 3600 ? [Math.round(abs / 60), "min"] : abs < 86400 ? [Math.round(abs / 3600), "h"] : [Math.round(abs / 86400), "d"];
  if (abs < 10) return "just now";
  return diff < 0 ? `${value} ${unit} ago` : `in ${value} ${unit}`;
}

export const hoursUntil = (iso: string) => (new Date(iso).getTime() - Date.now()) / 3_600_000;

export function duration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return "—";
  const s = (new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000;
  return s < 60 ? `${s.toFixed(1)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`;
}

export const initials = (name: string | null | undefined) =>
  (name ?? "?").split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";
