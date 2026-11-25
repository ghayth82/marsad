import { createContext, useRef, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Me, type Prefs } from "./api";

type Ctx = {
  me: Me | null;
  loading: boolean;
  needsSetup: boolean;
  setMe: (m: Me | null) => void;
  refresh: () => Promise<void>;
  savePrefs: (changes: Partial<Prefs>) => Promise<void>;
  logout: () => Promise<void>;
};

const SessionCtx = createContext<Ctx | null>(null);

function mergePrefs(base: Prefs, c: Partial<Prefs>): Prefs {
  return { ...base, ...c, ...(c.appearance ? { appearance: { ...base.appearance, ...c.appearance } } : {}) };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setMe(await api<Me>("/api/me"));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setMe(null);
        const s = await api<{ needs_setup: boolean }>("/api/setup").catch(() => ({ needs_setup: false }));
        setNeedsSetup(s.needs_setup);
      } else throw e;
    }
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  const seq = useRef(0);
  const savePrefs = useCallback(async (changes: Partial<Prefs>) => {
    // يظهر التغيير فورًا، ثم يُحفظ على الخادم فيتبع المستخدم إلى أي جهاز.
    // يُرسل المتغيّر وحده (الخادم يدمجه، والمظهر يُدمج حقلًا حقلًا)، فتغييران متتاليان سريعان لا يُلغي ثانيهما الأول.
    setMe((m) => (m ? { ...m, preferences: mergePrefs(m.preferences, changes) } : m));
    const mine = ++seq.current;
    const prefs = await api<Prefs>("/api/me/preferences", { method: "PATCH", body: changes });
    if (mine === seq.current) setMe((m) => (m ? { ...m, preferences: prefs } : m));  // ردّ أقدم لا يغطي اختيارًا أحدث
  }, []);

  const logout = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" });
    setMe(null);
  }, []);

  return (
    <SessionCtx.Provider value={{ me, loading, needsSetup, setMe: (m) => { setMe(m); if (m) setNeedsSetup(false); }, refresh, savePrefs, logout }}>
      {children}
    </SessionCtx.Provider>
  );
}

export function useSession(): Ctx {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("SessionProvider missing");
  return c;
}

export function useCan() {
  const { me } = useSession();
  return (p: string) => !!me?.access.effective.includes(p);
}
