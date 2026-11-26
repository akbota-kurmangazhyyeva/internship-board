"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { VacancyCard } from "@/components/VacancyCard";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { SavedItem } from "@/lib/types";

export default function Saved() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<SavedItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/saved");
    if (user) api.saved().then(setItems).catch((e) => setError(e.message));
  }, [ready, user, router]);

  return (
    <>
      <div className="page-head">
        <h1>Saved internships</h1>
        <p className="muted">Soonest deadline first. Unknown deadlines are at the bottom.</p>
      </div>
      {error && (
        <div className="notice error" role="alert">
          {error}
        </div>
      )}
      {!items && !error && <div className="card skeleton" aria-busy="true" />}
      {items && items.length === 0 && (
        <div className="notice">
          Nothing saved yet. Press ☆ Save on any internship and it will appear here. <Link href="/">Browse internships</Link>
        </div>
      )}
      <div className="list">
        {items?.map((s) => (
          <VacancyCard
            key={s.vacancy.id}
            card={s.vacancy}
            onSavedChange={(saved) => !saved && setItems((xs) => xs?.filter((x) => x.vacancy.id !== s.vacancy.id) ?? null)}
          />
        ))}
      </div>
    </>
  );
}
