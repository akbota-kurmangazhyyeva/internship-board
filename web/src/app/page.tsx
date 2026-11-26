"use client";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { FilterPanel } from "@/components/FilterPanel";
import { VacancyList } from "@/components/VacancyList";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { filtersToQuery, queryToFilters, SORT_LABEL } from "@/lib/format";
import { useFilterMeta } from "@/lib/hooks";
import type { Page, VacancyCard, VacancyFilters } from "@/lib/types";

const LIMIT = 20;

function Browse() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const meta = useFilterMeta();
  const { user, ready } = useAuth();

  const filters = queryToFilters(new URLSearchParams(params.toString()));
  const offset = Number(params.get("offset") || 0);
  const [q, setQ] = useState(filters.q ?? "");
  const [data, setData] = useState<Page<VacancyCard> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showFilters, setShowFilters] = useState(false);

  const key = params.toString();
  useEffect(() => {
    if (!ready) return;
    let stale = false;
    setLoading(true);
    setError(null);
    api
      .vacancies(filters, LIMIT, offset)
      .then((d) => !stale && setData(d))
      .catch((e) => !stale && setError(e.message))
      .finally(() => !stale && setLoading(false));
    return () => {
      stale = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready, user?.id]);

  const go = (f: VacancyFilters, newOffset = 0) => {
    const p = filtersToQuery(f);
    if (newOffset) p.set("offset", String(newOffset));
    router.push(`${path}?${p.toString()}`, { scroll: newOffset > 0 });
  };

  const sorts = ["newest", "deadline", ...(filters.q ? ["relevance"] : []), ...(user ? ["fit"] : [])];

  return (
    <>
      <section className="hero">
        <h1>Find an internship in Kazakhstan</h1>
        <p className="muted">
          One list from company sites, hh.kz and student channels. Each job is shown once, with its real deadline when the
          posting states one.
        </p>
        <form
          className="search"
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            go({ ...filters, q: q.trim() || undefined, sort: q.trim() ? filters.sort : filters.sort === "relevance" ? undefined : filters.sort });
          }}
        >
          <label htmlFor="q" className="sr-only">
            Search internships
          </label>
          <input
            id="q"
            className="input input-lg"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Python, data analyst, стажировка, тағылымдама…"
          />
          <button className="btn btn-primary btn-lg" type="submit">
            Search
          </button>
        </form>
        {ready && !user && (
          <p className="small">
            <Link href="/register">Create a profile</Link> to see internships ranked for you, with reasons.
          </p>
        )}
      </section>

      <div className="layout">
        <div className={showFilters ? "filters-wrap open" : "filters-wrap"}>
          <FilterPanel meta={meta} value={filters} onChange={(f) => go(f)} />
        </div>
        <section aria-label="Results">
          <div className="results-bar">
            <p className="muted" aria-live="polite">
              {data ? `${data.total} ${data.total === 1 ? "internship" : "internships"}` : " "}
            </p>
            <div className="results-controls">
              <button type="button" className="btn btn-outline btn-sm show-sm" onClick={() => setShowFilters(!showFilters)} aria-expanded={showFilters}>
                Filters
              </button>
              <label className="small muted" htmlFor="sort">
                Sort
              </label>
              <select
                id="sort"
                className="input select"
                value={filters.sort ?? ""}
                onChange={(e) => go({ ...filters, sort: (e.target.value || undefined) as VacancyFilters["sort"] })}
              >
                <option value="">Default</option>
                {sorts.map((s) => (
                  <option key={s} value={s}>
                    {SORT_LABEL[s]}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <VacancyList
            items={data?.items ?? []}
            total={data?.total ?? 0}
            offset={offset}
            limit={LIMIT}
            loading={loading}
            error={error}
            onPage={(o) => go(filters, o)}
            empty={
              <>
                <strong>No internships match.</strong> Try removing a filter or searching in another language (e.g.
                &quot;стажер&quot; as well as &quot;intern&quot;).
              </>
            }
          />
        </section>
      </div>
    </>
  );
}

export default function Home() {
  return (
    <Suspense>
      <Browse />
    </Suspense>
  );
}
