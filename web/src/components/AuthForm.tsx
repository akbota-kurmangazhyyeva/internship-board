"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { login, register } = useAuth();
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (isLogin) await login(email, password);
      else await register(email, password);
      // only same-site paths, never an external redirect
      router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : isLogin ? "/feed" : "/profile?welcome=1");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth card">
      <h1>{isLogin ? "Log in" : "Create your account"}</h1>
      <p className="muted">
        {isLogin ? "Welcome back." : "Then tell us your skills and cities, and we'll rank internships for you."}
      </p>
      <form onSubmit={submit} noValidate={false}>
        <div className="field">
          <label htmlFor="email" className="field-label">
            Email
          </label>
          <input id="email" className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="password" className="field-label">
            Password
          </label>
          <input
            id="password"
            className="input"
            type="password"
            autoComplete={isLogin ? "current-password" : "new-password"}
            required
            minLength={isLogin ? undefined : 8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-describedby={isLogin ? undefined : "pw-hint"}
          />
          {!isLogin && (
            <p id="pw-hint" className="hint">
              At least 8 characters.
            </p>
          )}
        </div>
        {error && (
          <p role="alert" className="notice error">
            {error}
          </p>
        )}
        <button className="btn btn-primary btn-block" disabled={busy}>
          {busy ? "Please wait…" : isLogin ? "Log in" : "Create account"}
        </button>
      </form>
      <p className="small">
        {isLogin ? (
          <>
            No account? <Link href={`/register${next ? `?next=${encodeURIComponent(next)}` : ""}`}>Sign up</Link>
          </>
        ) : (
          <>
            Already registered? <Link href="/login">Log in</Link>
          </>
        )}
      </p>
    </div>
  );
}
