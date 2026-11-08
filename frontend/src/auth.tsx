import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, setToken, getToken } from "./api";
import { live } from "./ws";
import type { Role, User } from "./types";

interface AuthCtx {
  user: User | null;
  ready: boolean;
  login: (token: string, user: User) => void;
  logout: () => void;
  can: (role: Role) => boolean;
}

const Ctx = createContext<AuthCtx>(null as unknown as AuthCtx);
const LEVEL: Record<Role, number> = { viewer: 0, trader: 1, admin: 2 };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    setToken(null);
    live.stop();
    setUser(null);
  }, []);

  const login = useCallback((token: string, u: User) => {
    setToken(token);
    setUser(u);
    live.stop();
    live.start();
  }, []);

  useEffect(() => {
    const onLogout = () => logout();
    window.addEventListener("ato:logout", onLogout);
    if (getToken()) {
      api<User>("/api/auth/me")
        .then((u) => {
          setUser(u);
          live.start();
        })
        .catch(() => setToken(null))
        .finally(() => setReady(true));
    } else {
      setReady(true);
    }
    return () => window.removeEventListener("ato:logout", onLogout);
  }, [logout]);

  const can = useCallback((role: Role) => !!user && LEVEL[user.role] >= LEVEL[role], [user]);

  return <Ctx.Provider value={{ user, ready, login, logout, can }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
