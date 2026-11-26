"use client";
import type { VacancyCard as Card } from "@/lib/types";
import { VacancyCard } from "./VacancyCard";

export function VacancyList({
  items,
  total,
  offset,
  limit,
  loading,
  error,
  onPage,
  empty,
}: {
  items: Card[];
  total: number;
  offset: number;
  limit: number;
  loading: boolean;
  error: string | null;
  onPage: (offset: number) => void;
  empty: React.ReactNode;
}) {
  if (error)
    return (
      <div className="notice error" role="alert">
        {error}
      </div>
    );
  if (loading && items.length === 0)
    return (
      <div className="list" aria-busy="true" aria-live="polite">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card skeleton" />
        ))}
      </div>
    );
  if (items.length === 0) return <div className="notice">{empty}</div>;

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <>
      <div className={loading ? "list loading" : "list"} aria-busy={loading}>
        {items.map((c) => (
          <VacancyCard key={c.id} card={c} />
        ))}
      </div>
      {pages > 1 && (
        <nav className="pager" aria-label="Pages">
          <button className="btn btn-outline" disabled={page <= 1} onClick={() => onPage(offset - limit)}>
            ← Previous
          </button>
          <span className="muted">
            Page {page} of {pages}
          </span>
          <button className="btn btn-outline" disabled={page >= pages} onClick={() => onPage(offset + limit)}>
            Next →
          </button>
        </nav>
      )}
    </>
  );
}
