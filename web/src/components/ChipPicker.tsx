"use client";
import { useId, useMemo, useState } from "react";

/** Multi-select with type-ahead. Options come from GET /meta/filters; `allowCustom` keeps free text (e.g. a rare skill). */
export function ChipPicker({
  label,
  options,
  value,
  onChange,
  labels,
  allowCustom = false,
  placeholder = "Type to search…",
  hint,
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (v: string[]) => void;
  labels?: Record<string, string>;
  allowCustom?: boolean;
  placeholder?: string;
  hint?: string;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const show = (v: string) => labels?.[v] ?? v;
  const matches = useMemo(() => {
    const t = text.trim().toLowerCase();
    if (!t) return [];
    // exact match first, then prefix matches, then substring: typing "SQL" should offer SQL before MS SQL Server
    const rank = (o: string) => {
      const s = show(o).toLowerCase();
      return s === t ? 0 : s.startsWith(t) ? 1 : 2;
    };
    return options
      .filter((o) => !value.includes(o) && show(o).toLowerCase().includes(t))
      .sort((a, b) => rank(a) - rank(b))
      .slice(0, 8);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, options, value]);

  const add = (v: string) => {
    const clean = v.trim();
    if (clean && !value.some((x) => x.toLowerCase() === clean.toLowerCase())) onChange([...value, clean]);
    setText("");
  };

  return (
    <div className="field">
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      {value.length > 0 && (
        <ul className="chips" aria-label={`Selected ${label.toLowerCase()}`}>
          {value.map((v) => (
            <li key={v} className="chip">
              {show(v)}
              <button type="button" aria-label={`Remove ${show(v)}`} onClick={() => onChange(value.filter((x) => x !== v))}>
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="typeahead">
        <input
          id={id}
          className="input"
          value={text}
          placeholder={placeholder}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (matches[0]) add(matches[0]);
              else if (allowCustom) add(text);
            }
          }}
          autoComplete="off"
          aria-describedby={hint ? `${id}-hint` : undefined}
        />
        {matches.length > 0 && (
          <ul className="suggestions" role="listbox" aria-label={`${label} suggestions`}>
            {matches.map((m) => (
              <li key={m} role="option" aria-selected={false}>
                <button type="button" onClick={() => add(m)}>
                  {show(m)}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {hint && (
        <p id={`${id}-hint`} className="hint">
          {hint}
        </p>
      )}
    </div>
  );
}

/** A row of toggle checkboxes for short fixed lists (formats, levels, languages). */
export function CheckGroup({
  legend,
  options,
  value,
  onChange,
  labels,
}: {
  legend: string;
  options: string[];
  value: string[];
  onChange: (v: string[]) => void;
  labels?: Record<string, string>;
}) {
  return (
    <fieldset className="field checkgroup">
      <legend className="field-label">{legend}</legend>
      <div className="check-row">
        {options.map((o) => (
          <label key={o} className={value.includes(o) ? "check on" : "check"}>
            <input
              type="checkbox"
              checked={value.includes(o)}
              onChange={(e) => onChange(e.target.checked ? [...value, o] : value.filter((x) => x !== o))}
            />
            {labels?.[o] ?? o}
          </label>
        ))}
      </div>
    </fieldset>
  );
}
