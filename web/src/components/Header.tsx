"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

const LINKS = [
  { href: "/", label: "Browse" },
  { href: "/feed", label: "For you", auth: true },
  { href: "/saved", label: "Saved", auth: true },
  { href: "/profile", label: "Profile", auth: true },
];

export function Header() {
  const { user, ready, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();

  return (
    <header className="site-header">
      <div className="container header-inner">
        <Link href="/" className="brand" aria-label="Internship Board home">
          <span className="brand-mark" aria-hidden>
            ◆
          </span>
          Internship Board <span className="brand-kz">KZ</span>
        </Link>
        <nav aria-label="Main">
          <ul className="nav-list">
            {LINKS.filter((l) => !l.auth || user).map((l) => {
              const active = l.href === "/" ? path === "/" : path.startsWith(l.href);
              return (
                <li key={l.href}>
                  <Link href={l.href} className={active ? "nav-link active" : "nav-link"} aria-current={active ? "page" : undefined}>
                    {l.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="header-actions">
          {!ready ? null : user ? (
            <>
              <span className="muted small hide-sm">{user.email}</span>
              <button
                className="btn btn-ghost"
                onClick={() => {
                  logout();
                  router.push("/");
                }}
              >
                Log out
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="btn btn-ghost">
                Log in
              </Link>
              <Link href="/register" className="btn btn-primary">
                Sign up
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
