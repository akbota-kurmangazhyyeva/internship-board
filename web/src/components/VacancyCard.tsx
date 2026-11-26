import Link from "next/link";
import type { VacancyCard as Card } from "@/lib/types";
import { deadlineLabel, FORMAT_LABEL, formatSalary, LEVEL_LABEL, relativeTime, UNKNOWN } from "@/lib/format";
import { SaveButton } from "./SaveButton";

export function Unknown({ label = UNKNOWN }: { label?: string }) {
  return (
    <span className="unknown" title="Not stated in the posting, or not extracted with enough confidence">
      {label}
    </span>
  );
}

function FitBadge({ card }: { card: Card }) {
  if (!card.fit) return null;
  const score = Math.round(card.fit.score);
  const tone = !card.fit.eligible ? "fit-low" : score >= 70 ? "fit-high" : score >= 40 ? "fit-mid" : "fit-low";
  return (
    <div className={`fit ${tone}`} title={card.fit.eligible ? "Fit with your profile" : "Doesn't meet one of your must-haves"}>
      <span className="fit-score">{score}</span>
      <span className="fit-label">fit</span>
    </div>
  );
}

export function VacancyCard({ card, onSavedChange }: { card: Card; onSavedChange?: (saved: boolean) => void }) {
  const dl = deadlineLabel(card.deadline);
  const salary = card.salary ? formatSalary(card.salary) : null;
  return (
    <article className="card vacancy-card" aria-labelledby={`v-${card.id}-title`}>
      <div className="vacancy-main">
        <div className="vacancy-top">
          <div>
            <h3 id={`v-${card.id}-title`} className="vacancy-title">
              <Link href={`/vacancies/${card.id}`}>{card.title}</Link>
            </h3>
            <p className="employer">{card.employer ?? <Unknown label="Employer unknown" />}</p>
          </div>
          <FitBadge card={card} />
        </div>

        <ul className="meta-row" aria-label="Key facts">
          <li className="tag tag-level">{card.level ? LEVEL_LABEL[card.level] : <Unknown label="Level unknown" />}</li>
          {card.is_internship && <li className="tag tag-intern">Internship</li>}
          <li className="tag">{card.work_format ? FORMAT_LABEL[card.work_format] : <Unknown label="Format unknown" />}</li>
          <li className="tag">{card.cities.length ? card.cities.join(", ") : <Unknown label="City unknown" />}</li>
          {salary && <li className="tag tag-salary">{salary}</li>}
        </ul>

        {card.skills.length > 0 && (
          <ul className="skills" aria-label="Skills">
            {card.skills.slice(0, 8).map((s) => (
              <li key={s} className="skill">
                {s}
              </li>
            ))}
            {card.skills.length > 8 && <li className="skill skill-more">+{card.skills.length - 8}</li>}
          </ul>
        )}

        {card.fit && card.fit.summary && (
          <p className={card.fit.eligible ? "fit-summary" : "fit-summary warn"}>
            {card.fit.eligible ? "Why: " : "Heads-up: "}
            {card.fit.eligible ? card.fit.summary : card.fit.violations.map((v) => v.text).join(" · ") || card.fit.summary}
          </p>
        )}
      </div>

      <footer className="vacancy-foot">
        <span className={dl.urgent ? "deadline urgent" : card.deadline ? "deadline" : "deadline unknown-dl"}>{dl.text}</span>
        <span className="muted small">
          {card.sources.length > 1 ? `${card.sources.length} sources` : card.sources[0]} · checked {relativeTime(card.last_checked_at)}
        </span>
        {card.is_saved !== null && <SaveButton id={card.id} saved={!!card.is_saved} compact onChange={onSavedChange} />}
      </footer>
    </article>
  );
}
