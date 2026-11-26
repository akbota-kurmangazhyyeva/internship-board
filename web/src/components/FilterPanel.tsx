"use client";
import type { FiltersMeta, VacancyFilters } from "@/lib/types";
import { activeFilterCount, FORMAT_LABEL, LANGUAGE_LABEL, LEVEL_LABEL } from "@/lib/format";
import { CheckGroup, ChipPicker } from "./ChipPicker";

export function FilterPanel({
  meta,
  value,
  onChange,
}: {
  meta: FiltersMeta | null;
  value: VacancyFilters;
  onChange: (f: VacancyFilters) => void;
}) {
  const set = (patch: Partial<VacancyFilters>) => onChange({ ...value, ...patch });
  const n = activeFilterCount(value);
  return (
    <aside className="filters card" aria-label="Filters">
      <div className="filters-head">
        <h2 className="h-small">Filters</h2>
        {n > 0 && (
          <button
            type="button"
            className="link-btn"
            onClick={() => onChange({ q: value.q, sort: value.sort })}
          >
            Clear {n}
          </button>
        )}
      </div>

      <label className="check single">
        <input type="checkbox" checked={!!value.internship_only} onChange={(e) => set({ internship_only: e.target.checked || undefined })} />
        Internships only
      </label>

      <ChipPicker label="Skills" options={meta?.skills ?? []} value={value.skill ?? []} onChange={(v) => set({ skill: v })} placeholder="Python, SQL, Figma…" />
      <ChipPicker label="City" options={meta?.cities ?? []} value={value.city ?? []} onChange={(v) => set({ city: v })} placeholder="Almaty, Astana…" />
      <CheckGroup legend="Work format" options={meta?.work_formats ?? ["remote", "hybrid", "onsite"]} labels={FORMAT_LABEL} value={value.work_format ?? []} onChange={(v) => set({ work_format: v })} />
      <CheckGroup legend="Level" options={meta?.levels ?? ["intern", "junior"]} labels={LEVEL_LABEL} value={value.level ?? []} onChange={(v) => set({ level: v })} />
      <CheckGroup legend="Language required" options={meta?.languages ?? ["kk", "ru", "en"]} labels={LANGUAGE_LABEL} value={value.language ?? []} onChange={(v) => set({ language: v })} />

      <fieldset className="field">
        <legend className="field-label">Deadline between</legend>
        <div className="date-row">
          <input type="date" className="input" aria-label="Deadline from" value={value.deadline_from ?? ""} onChange={(e) => set({ deadline_from: e.target.value || undefined })} />
          <span aria-hidden>–</span>
          <input type="date" className="input" aria-label="Deadline to" value={value.deadline_to ?? ""} onChange={(e) => set({ deadline_to: e.target.value || undefined })} />
        </div>
        <p className="hint">Postings with an unknown deadline are hidden when you set this.</p>
      </fieldset>
    </aside>
  );
}
