"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { SaveButton } from "@/components/SaveButton";
import { Unknown } from "@/components/VacancyCard";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import {
  deadlineLabel,
  formatDate,
  FORMAT_LABEL,
  formatSalary,
  htmlToText,
  LANGUAGE_LABEL,
  LEVEL_LABEL,
  relativeTime,
} from "@/lib/format";
import type { FieldMeta, VacancyDetail } from "@/lib/types";

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const METHOD_LABEL: Record<string, string> = { source: "Given by the source", rule: "Found in the text", admin: "Checked by a moderator" };

function Provenance({ meta }: { meta?: FieldMeta }) {
  if (!meta || (!meta.evidence && meta.confidence == null)) return null;
  const kind = meta.method?.split(":")[0] ?? "";
  return (
    <details className="provenance">
      <summary>How we know</summary>
      <p className="small">
        {METHOD_LABEL[kind] ?? meta.method}
        {meta.confidence != null && ` · confidence ${Math.round(meta.confidence * 100)}%`}
        {meta.status !== "ok" && ` · ${meta.status.replace("_", " ")}`}
      </p>
      {meta.evidence && <blockquote className="evidence">{meta.evidence.replaceAll("⏎", "↵")}</blockquote>}
    </details>
  );
}

function Fact({ label, children, meta }: { label: string; children: React.ReactNode; meta?: FieldMeta }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>
        {children}
        <Provenance meta={meta} />
      </dd>
    </div>
  );
}

export default function VacancyPage() {
  const { id } = useParams<{ id: string }>();
  const { user, ready } = useAuth();
  const [v, setV] = useState<VacancyDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!ready) return;
    api
      .vacancy(id)
      .then((d) => {
        setV(d);
        if (user) api.interact(d.id, "view").catch(() => undefined); // stored only if the student consented
      })
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? "This internship doesn't exist or was removed." : e.message));
  }, [id, ready, user]);

  if (error)
    return (
      <div className="notice error" role="alert">
        {error} <Link href="/">Back to all internships</Link>
      </div>
    );
  if (!v) return <div className="card skeleton tall" aria-busy="true" />;

  const dl = deadlineLabel(v.deadline);
  const applyUrl = v.apply_url ?? v.source_links.find((s) => s.live)?.url ?? v.source_links[0]?.url;
  const elig = v.eligibility;
  const years =
    elig && (elig.min_year || elig.max_year)
      ? elig.min_year && elig.max_year
        ? `Year ${elig.min_year}–${elig.max_year} students`
        : elig.min_year
          ? `Year ${elig.min_year}+ students`
          : `Up to year ${elig.max_year}`
      : null;

  return (
    <article className="detail">
      <p>
        <Link href="/" className="small">
          ← All internships
        </Link>
      </p>
      {v.status !== "active" && (
        <div className="notice warn">
          This posting is <strong>{v.status}</strong>. It may no longer accept applications.
        </div>
      )}
      <header className="detail-head card">
        <div>
          <h1>{v.title}</h1>
          <p className="employer lg">{v.employer ?? <Unknown label="Employer unknown" />}</p>
          <p className={dl.urgent ? "deadline urgent" : "deadline"}>{dl.text}</p>
        </div>
        <div className="detail-actions">
          {applyUrl && (
            <a
              className="btn btn-primary btn-lg"
              href={applyUrl}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => user && api.interact(v.id, "click_apply").catch(() => undefined)}
            >
              Apply ↗
            </a>
          )}
          {user ? (
            <SaveButton id={v.id} saved={!!v.is_saved} />
          ) : (
            <Link className="btn btn-outline" href={`/login?next=/vacancies/${v.id}`}>
              Log in to save
            </Link>
          )}
        </div>
      </header>

      {v.fit && (
        <section className={v.fit.eligible ? "card fit-box" : "card fit-box warn"} aria-label="Fit with your profile">
          <h2 className="h-small">
            Fit with your profile: {Math.round(v.fit.score)}/100{!v.fit.eligible && " · doesn't meet a must-have"}
          </h2>
          <ul className="reasons">
            {[...v.fit.violations, ...v.fit.reasons].map((r, i) => (
              <li key={i} className={r.polarity > 0 ? "pos" : r.polarity < 0 ? "neg" : "neu"}>
                {r.text}
              </li>
            ))}
          </ul>
          {user && !dismissed && (
            <button
              className="link-btn small"
              onClick={() => api.interact(v.id, "not_relevant").then(() => setDismissed(true)).catch(() => undefined)}
            >
              Not relevant to me
            </button>
          )}
          {dismissed && <p className="small muted">Thanks, we&apos;ll use this to improve your ranking.</p>}
        </section>
      )}

      <div className="detail-grid">
        <section className="card" aria-label="Key facts">
          <h2 className="h-small">Key facts</h2>
          <dl className="facts">
            <Fact label="Type" meta={v.fields.is_internship}>
              {v.is_internship == null ? <Unknown /> : v.is_internship ? "Internship" : "Job (not an internship)"}
            </Fact>
            <Fact label="Level" meta={v.fields.level}>
              {v.level ? LEVEL_LABEL[v.level] : <Unknown />}
            </Fact>
            <Fact label="Work format" meta={v.fields.work_format}>
              {v.work_format ? FORMAT_LABEL[v.work_format] : <Unknown />}
            </Fact>
            <Fact label="City" meta={v.fields.cities}>
              {v.cities.length ? v.cities.join(", ") : <Unknown />}
            </Fact>
            <Fact label="Deadline" meta={v.fields.deadline}>
              {v.deadline ? formatDate(v.deadline) : <Unknown label="Not stated" />}
            </Fact>
            <Fact label="Pay" meta={v.fields.salary}>
              {v.salary ? formatSalary(v.salary) : <Unknown label="Not stated" />}
            </Fact>
            <Fact label="Who can apply" meta={v.fields.eligibility}>
              {years ?? <Unknown label="Not stated" />}
            </Fact>
            <Fact label="Languages" meta={v.fields.languages}>
              {v.languages.length ? v.languages.map((l) => LANGUAGE_LABEL[l] ?? l).join(", ") : <Unknown label="Not stated" />}
            </Fact>
            <Fact label="Skills" meta={v.fields.skills}>
              {v.skills.length ? (
                <ul className="skills">
                  {v.skills.map((s) => (
                    <li key={s} className="skill">
                      {s}
                    </li>
                  ))}
                </ul>
              ) : (
                <Unknown label="None listed" />
              )}
            </Fact>
          </dl>
        </section>

        <section className="card" aria-label="Where this is posted">
          <h2 className="h-small">Posted on</h2>
          <ul className="sources">
            {v.source_links.map((s) => (
              <li key={s.url}>
                <a href={s.url} target="_blank" rel="noopener noreferrer">
                  {s.source} ↗
                </a>
                <span className="small muted">{hostOf(s.url)}</span>
                <span className="small muted">
                  {s.live ? "live" : "no longer online"} · checked {relativeTime(s.last_checked_at)}
                </span>
              </li>
            ))}
          </ul>
          {v.source_links.length > 1 && (
            <p className="hint">We found this internship in {v.source_links.length} places and merged them into one card.</p>
          )}
          <p className="hint">Last checked {relativeTime(v.last_checked_at)}.</p>
        </section>
      </div>

      <section className="card" aria-label="Original description">
        <h2 className="h-small">Original posting</h2>
        <div className="description" lang={v.posting_language ?? undefined}>
          {htmlToText(v.description)}
        </div>
      </section>
    </article>
  );
}
