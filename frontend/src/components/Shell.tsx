import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { visibleSections, SECTIONS } from "../nav";
import { useSession } from "../session";
import { Frame } from "./Frame";
import { HistoryNav } from "./HistoryNav";
import { ReaderDrawer } from "./Reader";

export function Shell() {
  const { me, savePrefs } = useSession();
  const loc = useLocation();
  const nav = useNavigate();
  if (!me) return null;
  const p = me.preferences;
  const en = p.language === "en";
  const sections = visibleSections(me.access, p.view_as_role);
  const current = SECTIONS.find((s) => s.path !== "/" && loc.pathname.startsWith(s.path)) ?? SECTIONS[0];
  const activeRoles = me.access.roles.filter((r) => r.active);
  const dark = p.theme === "dark" || (p.theme === "system" && (p.pattern === "a" || !!window.matchMedia?.("(prefers-color-scheme: dark)").matches));

  return (
    <Frame prefs={p}>
      <nav className="nav" aria-label={en ? "Sections" : "الأقسام"}>
        <span className="logo" aria-hidden="true">{en ? "M" : "م"}</span>
        {sections.map((s) => (
          <NavLink key={s.path} to={s.path} end={s.path === "/"} className={({ isActive }) => (isActive ? "on" : "")}>
            {en ? s.en : s.ar}
          </NavLink>
        ))}
      </nav>
      <div className="main">
        <header className="top">
          <HistoryNav en={en} />
          <div style={{ display: "flex", flexDirection: "column", gap: 2, flex: "1 1 220px", minWidth: 0 }}>
            <span className="crumb">{me.full_name || me.email}</span>
            <h1>{/^\/me(\/|$)/.test(loc.pathname) ? (en ? "My preferences" : "تفضيلاتي") : en ? current.en : current.ar}</h1>
          </div>
          <form role="search" onSubmit={(e) => { e.preventDefault(); const q = new FormData(e.currentTarget).get("q"); nav(`/live?q=${encodeURIComponent(String(q ?? ""))}`); }}>
            <input className="search" name="q" type="search" placeholder={en ? "Search everything monitored…" : "ابحث في كل ما رُصد…"} aria-label={en ? "Search" : "بحث"} />
          </form>
          {activeRoles.length > 1 && (
            <label className="chk" style={{ fontWeight: 600 }}>
              <span>{en ? "View as" : "عرض كـ"}</span>
              <select className="inp" style={{ height: 36, width: "auto" }} value={p.view_as_role ?? ""}
                onChange={(e) => savePrefs({ view_as_role: e.target.value || null })}>
                <option value="">{en ? "All my roles" : "كل أدواري"}</option>
                {activeRoles.map((r) => <option key={r.key} value={r.key}>{r.name_ar}</option>)}
              </select>
            </label>
          )}
          <button className="mode-btn" onClick={() => savePrefs({ theme: dark ? "light" : "dark", pattern: "c" })}
            title={dark ? (en ? "Switch to light" : "التبديل إلى الفاتح") : (en ? "Switch to dark" : "التبديل إلى الداكن")}
            aria-label={dark ? (en ? "Light mode" : "الوضع الفاتح") : (en ? "Dark mode" : "الوضع الداكن")}>{dark ? "☀" : "☾"}</button>
          <button className="av" title={en ? "My preferences" : "تفضيلاتي"} aria-label={en ? "My preferences" : "تفضيلاتي"}
            onClick={() => nav("/me")}>{(me.full_name || me.email).trim().charAt(0).toUpperCase()}</button>
        </header>
        <main className="body">
          <Outlet />
          <ReaderDrawer />
        </main>
      </div>
    </Frame>
  );
}
