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
import { Claims } from "./pages/claims/ClaimCard";
import { Rumors } from "./pages/claims/Rumors";
import { AudioLab } from "./pages/labs/AudioLab";
import { Ratings } from "./pages/ratings/Ratings";
import { Cases } from "./pages/cases/Cases";
import { Help } from "./pages/Help";
import { Reports } from "./pages/reports/Reports";
import { Training } from "./pages/training/Training";
import { StoryBuilder } from "./pages/cases/StoryBuilder";
import { MediaLab } from "./pages/labs/MediaLab";
import { Live } from "./pages/monitor/Live";
import { Sources } from "./pages/monitor/Sources";
import { AcceptInvite, Login, Setup } from "./pages/Auth";
import { Dashboard, Placeholder } from "./pages/Dashboard";
import { Preferences } from "./pages/Preferences";
import { SessionProvider, useSession } from "./session";

// الأقسام المبنية؛ ما عداها صفحة «قيد البناء» إلى أن يُبنى.
const BUILT = new Set(["/", "/admin", "/engines", "/sources", "/live", "/stories", "/entities", "/rumors", "/claims", "/media-lab", "/audio-lab", "/ratings", "/cases", "/story-builder", "/reports", "/training", "/help"]);

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
        <Route path="rumors" element={allowed.has("/rumors") ? <Rumors /> : <Navigate to="/" replace />} />
        <Route path="media-lab/:id?" element={allowed.has("/media-lab") ? <MediaLab /> : <Navigate to="/" replace />} />
        <Route path="audio-lab/:id?" element={allowed.has("/audio-lab") ? <AudioLab /> : <Navigate to="/" replace />} />
        <Route path="cases/*" element={allowed.has("/cases") || allowed.has("/story-builder") ? <Cases /> : <Navigate to="/" replace />} />
        <Route path="story-builder/:id?" element={allowed.has("/story-builder") || allowed.has("/cases") ? <StoryBuilder /> : <Navigate to="/" replace />} />
        <Route path="reports/:id?" element={allowed.has("/reports") ? <Reports /> : <Navigate to="/" replace />} />
        <Route path="training/:id?" element={allowed.has("/training") ? <Training /> : <Navigate to="/" replace />} />
        <Route path="help" element={<Help />} />
        <Route path="ratings/*" element={allowed.has("/ratings") ? <Ratings /> : <Navigate to="/" replace />} />
        <Route path="claims/*" element={allowed.has("/claims") || allowed.has("/rumors") ? <Claims /> : <Navigate to="/" replace />} />
        {SECTIONS.filter((s) => !BUILT.has(s.path)).map((s) => (
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
