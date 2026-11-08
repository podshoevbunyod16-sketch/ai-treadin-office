import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api } from "./api";
import { useTopic } from "./hooks";
import type { Account, Runtime } from "./types";

interface Ctx {
  accounts: Account[];
  loaded: boolean;
  error: string | null;
  reload: () => Promise<void>;
}

const AccountsCtx = createContext<Ctx>({ accounts: [], loaded: false, error: null, reload: async () => {} });

export function AccountsProvider({ children }: { children: ReactNode }) {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      setAccounts(await api<Account[]>("/api/accounts"));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useTopic("accounts", (m) => {
    if (m.type !== "status") return;
    const rt = m.data as Runtime;
    setAccounts((xs) => xs.map((a) => (a.id === rt.account_id ? { ...a, runtime: { ...a.runtime, ...rt } } : a)));
  });

  return <AccountsCtx.Provider value={{ accounts, loaded, error, reload }}>{children}</AccountsCtx.Provider>;
}

export const useAccounts = () => useContext(AccountsCtx);
