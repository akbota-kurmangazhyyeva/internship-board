"use client";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";
import type { User } from "./types";

interface AuthState {
  user: User | null;
  ready: boolean; // false until we know whether a stored token is still valid
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      setReady(true);
      return;
    }
    try {
      setUser(await api.me());
    } catch {
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onChange = () => refresh();
    window.addEventListener("ib-auth", onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener("ib-auth", onChange);
      window.removeEventListener("storage", onChange);
    };
  }, [refresh]);

  // Wait until the user is loaded before resolving, so the next page never sees "logged out" for a moment.
  const login = async (email: string, password: string) => {
    setToken((await api.login(email, password)).access_token);
    await refresh();
  };
  const register = async (email: string, password: string) => {
    setToken((await api.register(email, password)).access_token);
    await refresh();
  };
  const logout = () => setToken(null);

  return <AuthContext.Provider value={{ user, ready, login, register, logout, refresh }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
