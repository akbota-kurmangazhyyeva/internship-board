// Display helpers. Pure functions, unit-tested in format.test.ts.
import type { Salary, VacancyFilters } from "./types.ts";

export const UNKNOWN = "Unknown";

export const LEVEL_LABEL: Record<string, string> = { intern: "Intern", junior: "Junior", mid: "Middle", senior: "Senior" };
export const FORMAT_LABEL: Record<string, string> = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" };
export const LANGUAGE_LABEL: Record<string, string> = { kk: "Kazakh", ru: "Russian", en: "English" };
export const SORT_LABEL: Record<string, string> = {
  relevance: "Best match for search",
  newest: "Newest",
  deadline: "Deadline soonest",
  fit: "Best fit for me",
};

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-12-15" → "15 Dec 2026". Dates are calendar dates in Kazakhstan (UTC+5), never shifted by the browser. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return UNKNOWN;
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return UNKNOWN;
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

/** Whole days from `today` (YYYY-MM-DD in KZ time) to `deadline`; negative if passed. */
export function daysUntil(deadline: string, today: string = kzToday()): number {
  const a = Date.UTC(+today.slice(0, 4), +today.slice(5, 7) - 1, +today.slice(8, 10));
  const b = Date.UTC(+deadline.slice(0, 4), +deadline.slice(5, 7) - 1, +deadline.slice(8, 10));
  return Math.round((b - a) / 86_400_000);
}

export function kzToday(now: Date = new Date()): string {
  return new Date(now.getTime() + 5 * 3_600_000).toISOString().slice(0, 10);
}

export function deadlineLabel(deadline: string | null, today?: string): { text: string; urgent: boolean } {
  if (!deadline) return { text: "Deadline unknown", urgent: false };
  const days = daysUntil(deadline, today);
  if (days < 0) return { text: `Closed ${formatDate(deadline)}`, urgent: false };
  if (days === 0) return { text: "Closes today", urgent: true };
  if (days <= 7) return { text: `Closes in ${days} day${days === 1 ? "" : "s"}`, urgent: true };
  return { text: `Apply by ${formatDate(deadline)}`, urgent: false };
}

function num(n: number): string {
  return n.toLocaleString("en-US").replace(/,/g, " ");
}

export function formatSalary(s: Salary | null | undefined): string {
  if (!s) return UNKNOWN;
  if (s.unpaid) return "Unpaid";
  const cur = s.currency ? ` ${s.currency}` : "";
  const per = s.period ? ` / ${s.period}` : "";
  if (s.min != null && s.max != null) return s.min === s.max ? `${num(s.min)}${cur}${per}` : `${num(s.min)}–${num(s.max)}${cur}${per}`;
  if (s.min != null) return `from ${num(s.min)}${cur}${per}`;
  if (s.max != null) return `up to ${num(s.max)}${cur}${per}`;
  return s.text || UNKNOWN;
}

export function relativeTime(iso: string, now: Date = new Date()): string {
  const mins = Math.round((now.getTime() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const h = Math.round(mins / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return `${d} day${d === 1 ? "" : "s"} ago`;
}

const LIST_KEYS = ["skill", "city", "work_format", "level", "language"] as const;

/** Filters ↔ URL query string, so a search can be bookmarked and shared. */
export function filtersToQuery(f: VacancyFilters): URLSearchParams {
  const p = new URLSearchParams();
  if (f.q) p.set("q", f.q);
  for (const k of LIST_KEYS) for (const v of f[k] ?? []) p.append(k, v);
  if (f.deadline_from) p.set("deadline_from", f.deadline_from);
  if (f.deadline_to) p.set("deadline_to", f.deadline_to);
  if (f.internship_only) p.set("internship_only", "true");
  if (f.sort) p.set("sort", f.sort);
  return p;
}

export function queryToFilters(p: URLSearchParams): VacancyFilters {
  const f: VacancyFilters = {};
  const q = p.get("q");
  if (q) f.q = q;
  for (const k of LIST_KEYS) {
    const vals = p.getAll(k);
    if (vals.length) f[k] = vals;
  }
  const df = p.get("deadline_from");
  const dt = p.get("deadline_to");
  if (df) f.deadline_from = df;
  if (dt) f.deadline_to = dt;
  if (p.get("internship_only") === "true") f.internship_only = true;
  const sort = p.get("sort");
  if (sort && sort in SORT_LABEL) f.sort = sort as VacancyFilters["sort"];
  return f;
}

export function activeFilterCount(f: VacancyFilters): number {
  return LIST_KEYS.reduce((n, k) => n + (f[k]?.length ?? 0), 0) + (f.deadline_from ? 1 : 0) + (f.deadline_to ? 1 : 0) + (f.internship_only ? 1 : 0);
}

/** Strip tags from source HTML for safe plain-text display, keeping paragraph and list breaks. */
export function htmlToText(html: string): string {
  return html
    .replace(/<(script|style)[^>]*>[\s\S]*?<\/\1>/gi, "")
    .replace(/<\s*(br|\/p|\/li|\/div|\/h\d)\s*\/?>/gi, "\n")
    .replace(/<\s*li[^>]*>/gi, "• ")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
