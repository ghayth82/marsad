import "@fontsource/noto-sans-arabic/400.css";
import "@fontsource/noto-sans-arabic/600.css";
import "@fontsource/noto-sans-arabic/700.css";
import "@fontsource/readex-pro/400.css";
import "@fontsource/readex-pro/600.css";
import "@fontsource/readex-pro/700.css";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import "@fontsource/ibm-plex-sans-arabic/700.css";
import "./theme.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Shell } from "./components/Shell";
import { SECTIONS, visibleSections } from "./nav";
import { Admin } from "./pages/admin/Admin";
import { Engines } from "./pages/engines/Engines";
import { Entities } from "./pages/analysis/Entities";
import { Stories } from "./pages/analysis/Stories";
import { Live } from "./pages/monitor/Live";
import { Sources } from "./pages/monitor/Sources";
import { AcceptInvite, Login, Setup } from "./pages/Auth";
import { Dashboard, Placeholder } from "./pages/Dashboard";
import { Preferences } from "./pages/Preferences";
import { SessionProvider, useSession } from "./session";

function Routed() {
  const { me, loading, needsSetup } = useSession();
  const loc = useLocation();
  if (loading) return null;
  if (loc.pathname === "/invite") return <AcceptInvite />;
  if (!me) return needsSetup ? <Setup /> : <Login />;
  const allowed = new Set(visibleSections(me.access, null).map((s) => s.path));
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Dashboard />} />
        <Route path="me" element={<Preferences />} />
        <Route path="admin/*" element={allowed.has("/admin") ? <Admin /> : <Navigate to="/" replace />} />
        <Route path="engines/*" element={allowed.has("/engines") ? <Engines /> : <Navigate to="/" replace />} />
        <Route path="sources" element={allowed.has("/sources") ? <Sources /> : <Navigate to="/" replace />} />
        <Route path="live" element={allowed.has("/live") ? <Live /> : <Navigate to="/" replace />} />
        <Route path="stories/*" element={allowed.has("/stories") ? <Stories /> : <Navigate to="/" replace />} />
        <Route path="entities/*" element={allowed.has("/entities") ? <Entities /> : <Navigate to="/" replace />} />
        {SECTIONS.filter((s) => !["/", "/admin", "/engines", "/sources", "/live", "/stories", "/entities"].includes(s.path)).map((s) => (
          <Route key={s.path} path={s.path.slice(1) + "/*"} element={allowed.has(s.path) ? <Placeholder title={s.ar} /> : <Navigate to="/" replace />} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <Routed />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
);
