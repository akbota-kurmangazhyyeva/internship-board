// Thin typed client for the backend API (/api/v1). The base URL comes from NEXT_PUBLIC_API_URL.
import type {
  FeedPage,
  FiltersMeta,
  Page,
  Profile,
  SavedItem,
  User,
  VacancyCard,
  VacancyDetail,
  VacancyFilters,
} from "./types";
import { filtersToQuery } from "./format";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const TOKEN_KEY = "ib.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable (private mode): stay logged in for this tab only */
  }
  window.dispatchEvent(new Event("ib-auth"));
}

function detailMessage(body: unknown, status: number): string {
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length) {
    // FastAPI validation errors: [{loc: [...], msg: "..."}]
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = (d.loc ?? []).filter((x) => x !== "body").join(".");
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  return status >= 500 ? "The server had a problem. Please try again in a minute." : `Request failed (${status})`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  let resp: Response;
  try {
    resp = await fetch(`${API_URL}/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection.");
  }
  if (resp.status === 401 && token) setToken(null); // expired token: log out
  if (resp.status === 204) return undefined as T;
  const body = await resp.json().catch(() => null);
  if (!resp.ok) throw new ApiError(resp.status, detailMessage(body, resp.status));
  return body as T;
}

function query(f: VacancyFilters, limit: number, offset: number, omitSort = false): string {
  const p = filtersToQuery(omitSort ? { ...f, sort: undefined } : f);
  p.set("limit", String(limit));
  p.set("offset", String(offset));
  return p.toString();
}

export const api = {
  register: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  me: () => request<User>("/me"),
  deleteAccount: () => request<void>("/me", { method: "DELETE" }),
  setConsent: (tracking: boolean) => request<User>("/me/consent", { method: "PUT", body: JSON.stringify({ tracking }) }),

  vacancies: (f: VacancyFilters, limit = 20, offset = 0) => request<Page<VacancyCard>>(`/vacancies?${query(f, limit, offset)}`),
  feed: (f: VacancyFilters, limit = 20, offset = 0) => request<FeedPage>(`/feed?${query(f, limit, offset, true)}`),
  vacancy: (id: number | string) => request<VacancyDetail>(`/vacancies/${id}`),
  filters: () => request<FiltersMeta>("/meta/filters"),

  getProfile: () => request<Profile>("/me/profile"),
  putProfile: (p: Profile) => request<Profile>("/me/profile", { method: "PUT", body: JSON.stringify(p) }),

  saved: () => request<SavedItem[]>("/me/saved"),
  save: (id: number) => request<SavedItem>(`/me/saved/${id}`, { method: "PUT", body: JSON.stringify({ remind: true }) }),
  unsave: (id: number) => request<void>(`/me/saved/${id}`, { method: "DELETE" }),
  interact: (vacancy_id: number, kind: "view" | "click_apply" | "dismiss" | "not_relevant") =>
    request<{ recorded: boolean }>("/me/interactions", { method: "POST", body: JSON.stringify({ vacancy_id, kind }) }),
};
