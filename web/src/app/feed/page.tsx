"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { VacancyList } from "@/components/VacancyList";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { FeedPage } from "@/lib/types";

const LIMIT = 20;

export default function Feed() {
  const { user, ready } = useAuth();
  const router = useRouter();
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<FeedPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/feed");
  }, [ready, user, router]);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    api
      .feed({ internship_only: false }, LIMIT, offset)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user, offset]);

  return (
    <>
      <div className="page-head">
        <h1>For you</h1>
        <p className="muted">Ranked by how well each internship fits your profile. Each card says why.</p>
      </div>
      {data && !data.profile_complete && (
        <div className="notice info">
          Your profile is incomplete, so the ranking is rough. <Link href="/profile">Add your skills and cities</Link> for better matches.
        </div>
      )}
      {data?.relaxed && (
        <div className="notice warn">
          Nothing meets all of your must-haves right now, so these are the closest matches.
          {data.hint ? ` ${data.hint}` : ""}
        </div>
      )}
      <VacancyList
        items={data?.items ?? []}
        total={data?.total ?? 0}
        offset={offset}
        limit={LIMIT}
        loading={loading}
        error={error}
        onPage={(o) => {
          setOffset(o);
          window.scrollTo({ top: 0 });
        }}
        empty={
          <>
            No active internships yet. <Link href="/">Browse everything</Link> or check back after the next update.
          </>
        }
      />
    </>
  );
}
