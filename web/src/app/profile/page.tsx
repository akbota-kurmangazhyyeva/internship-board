"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { CheckGroup, ChipPicker } from "@/components/ChipPicker";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { FORMAT_LABEL, LANGUAGE_LABEL, LEVEL_LABEL } from "@/lib/format";
import { useFilterMeta } from "@/lib/hooks";
import type { Profile } from "@/lib/types";

const EMPTY: Profile = {
  education_level: "bachelor",
  year_of_study: null,
  expected_graduation_year: null,
  field_of_study: null,
  skills: [],
  preferred_cities: [],
  work_formats: [],
  target_levels: ["intern", "junior"],
  languages: [],
  interests: [],
  open_to_relocation: false,
};

const EDUCATION = { college: "College", bachelor: "Bachelor's", master: "Master's", phd: "PhD" };

function ProfileForm() {
  const { user, ready, refresh, logout } = useAuth();
  const router = useRouter();
  const welcome = useSearchParams().get("welcome");
  const meta = useFilterMeta();
  const [p, setP] = useState<Profile | null>(null);
  const [status, setStatus] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (ready && !user) router.replace("/login?next=/profile");
    if (!user) return;
    api
      .getProfile()
      .then(setP)
      .catch((e) => (e instanceof ApiError && e.status === 404 ? setP(EMPTY) : setStatus({ kind: "error", text: e.message })));
  }, [ready, user, router]);

  if (!p || !user) return <div className="card skeleton tall" aria-busy="true" />;
  const set = (patch: Partial<Profile>) => setP({ ...p, ...patch });

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!p) return;
    setBusy(true);
    setStatus(null);
    try {
      setP(await api.putProfile(p));
      setStatus({ kind: "ok", text: "Saved. Your feed is updated." });
      if (welcome) router.push("/feed");
    } catch (err) {
      setStatus({ kind: "error", text: err instanceof Error ? err.message : "Couldn't save" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-head">
        <h1>{welcome ? "Set up your profile" : "Your profile"}</h1>
        <p className="muted">Used only to rank internships for you. Leave anything blank that you don&apos;t want to share.</p>
      </div>

      <form className="profile-form" onSubmit={save}>
        <section className="card">
          <h2 className="h-small">Studies</h2>
          <div className="grid-3">
            <div className="field">
              <label htmlFor="edu" className="field-label">
                Degree
              </label>
              <select id="edu" className="input select" value={p.education_level ?? ""} onChange={(e) => set({ education_level: (e.target.value || null) as Profile["education_level"] })}>
                <option value="">Prefer not to say</option>
                {Object.entries(EDUCATION).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="year" className="field-label">
                Year of study
              </label>
              <select id="year" className="input select" value={p.year_of_study ?? ""} onChange={(e) => set({ year_of_study: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Not set</option>
                {[1, 2, 3, 4, 5, 6].map((y) => (
                  <option key={y} value={y}>
                    Year {y}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="grad" className="field-label">
                Graduation year
              </label>
              <input
                id="grad"
                className="input"
                type="number"
                min={2000}
                max={2100}
                value={p.expected_graduation_year ?? ""}
                onChange={(e) => set({ expected_graduation_year: e.target.value ? Number(e.target.value) : null })}
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="fos" className="field-label">
              Field of study
            </label>
            <input id="fos" className="input" maxLength={200} placeholder="Computer Science" value={p.field_of_study ?? ""} onChange={(e) => set({ field_of_study: e.target.value || null })} />
          </div>
        </section>

        <section className="card">
          <h2 className="h-small">What you can do</h2>
          <ChipPicker
            label="Skills"
            options={meta?.skills ?? []}
            value={p.skills}
            onChange={(v) => set({ skills: v })}
            allowCustom
            hint="Pick from the list or press Enter to add your own. Aliases like “postgres” are understood."
          />
          <CheckGroup legend="Languages you can work in" options={["kk", "ru", "en"]} labels={LANGUAGE_LABEL} value={p.languages} onChange={(v) => set({ languages: v as Profile["languages"] })} />
          <ChipPicker label="Interests" options={[]} value={p.interests} onChange={(v) => set({ interests: v })} allowCustom placeholder="fintech, data, design… press Enter" />
        </section>

        <section className="card">
          <h2 className="h-small">What you&apos;re looking for</h2>
          <CheckGroup legend="Level" options={["intern", "junior"]} labels={LEVEL_LABEL} value={p.target_levels} onChange={(v) => set({ target_levels: v as Profile["target_levels"] })} />
          <CheckGroup legend="Work format (leave empty for any)" options={["remote", "hybrid", "onsite"]} labels={FORMAT_LABEL} value={p.work_formats} onChange={(v) => set({ work_formats: v as Profile["work_formats"] })} />
          <ChipPicker label="Cities" options={meta?.cities ?? []} value={p.preferred_cities} onChange={(v) => set({ preferred_cities: v })} placeholder="Almaty, Astana…" />
          <label className="check single">
            <input type="checkbox" checked={p.open_to_relocation} onChange={(e) => set({ open_to_relocation: e.target.checked })} />
            I&apos;m open to moving to another city
          </label>
        </section>

        {status && (
          <p role={status.kind === "error" ? "alert" : "status"} className={`notice ${status.kind === "error" ? "error" : "success"}`}>
            {status.text}
          </p>
        )}
        <div className="form-actions">
          <button className="btn btn-primary btn-lg" disabled={busy}>
            {busy ? "Saving…" : welcome ? "Save and see my internships" : "Save profile"}
          </button>
        </div>
      </form>

      <section className="card privacy" aria-label="Privacy">
        <h2 className="h-small">Privacy</h2>
        <label className="check single">
          <input
            type="checkbox"
            checked={user.tracking_consent}
            onChange={async (e) => {
              await api.setConsent(e.target.checked);
              await refresh();
            }}
          />
          Use what I view and open to improve my ranking
        </label>
        <p className="hint">Off by default. Turning it off also deletes what was collected. Saves and &quot;not relevant&quot; clicks are always kept, because you asked for them.</p>
        <button
          type="button"
          className="btn btn-danger"
          onClick={async () => {
            if (!window.confirm("Delete your account, profile and saved internships? This can't be undone.")) return;
            await api.deleteAccount();
            logout();
            router.push("/");
          }}
        >
          Delete my account and data
        </button>
      </section>
    </>
  );
}

export default function ProfilePage() {
  return (
    <Suspense>
      <ProfileForm />
    </Suspense>
  );
}
