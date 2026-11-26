"use client";
import { useState } from "react";
import { api } from "@/lib/api";

export function SaveButton({
  id,
  saved: initial,
  compact = false,
  onChange,
}: {
  id: number;
  saved: boolean;
  compact?: boolean;
  onChange?: (saved: boolean) => void;
}) {
  const [saved, setSaved] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (saved) await api.unsave(id);
      else await api.save(id);
      setSaved(!saved);
      onChange?.(!saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <span className="save-wrap">
      <button
        type="button"
        className={`btn ${saved ? "btn-saved" : "btn-outline"} ${compact ? "btn-sm" : ""}`}
        onClick={toggle}
        disabled={busy}
        aria-pressed={saved}
        title={saved ? "Remove from saved" : "Save and get a reminder before the deadline"}
      >
        {saved ? "★ Saved" : "☆ Save"}
      </button>
      {error && (
        <span role="alert" className="error-text small">
          {error}
        </span>
      )}
    </span>
  );
}
