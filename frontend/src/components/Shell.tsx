import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { DEFAULT_APPEARANCE, type Prefs } from "../api";
import { GROUPS, navSections, SECTIONS } from "../nav";
import { Icon } from "./Icon";
import { HintLayer } from "../hints/HintLayer";
import { PAGE_INTRO } from "../hints/data";
import { Tour } from "./Tour";
import { useSession } from "../session";
import { Frame } from "./Frame";
import { HistoryNav } from "./HistoryNav";
import { ReaderDrawer } from "./Reader";

export function Shell() {
  const { me, savePrefs } = useSession();
  const loc = useLocation();
  const nav = useNavigate();
  const [tour, setTour] = useState(false);
  const welcome = new URLSearchParams(loc.search).has("welcome") || new URLSearchParams(loc.search).has("tour");
  const tourDone = me?.preferences.tour_done;
  // الجولة تُفتح وحدها بعد إنشاء الحساب أو قبول الدعوة، أو بطلبها (?tour=1)
  useEffect(() => { if (welcome && (!tourDone || new URLSearchParams(loc.search).has("tour"))) setTour(true); }, [welcome, tourDone]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!me) return null;
  const p = me.preferences;
  const en = p.language === "en";
  const sections = navSections(me.access, p.view_as_role);
  const ap = { ...DEFAULT_APPEARANCE, ...(p.appearance ?? {}) };
  const setAp = (c: Partial<typeof ap>) => savePrefs({ appearance: c } as unknown as Partial<Prefs>);
  const intro = PAGE_INTRO.find(([path]) => (path === "/" ? loc.pathname === "/" : loc.pathname.startsWith(path)));
  const current = SECTIONS.find((s) => s.path !== "/" && loc.pathname.startsWith(s.path)) ?? SECTIONS[0];
  const activeRoles = me.access.roles.filter((r) => r.active);
  const dark = p.theme === "dark" || (p.theme === "system" && (p.pattern === "a" || !!window.matchMedia?.("(prefers-color-scheme: dark)").matches));

  return (
    <Frame prefs={p}>
      <nav className="nav" aria-label={en ? "Sections" : "الأقسام"}>
        <span className="logo" aria-hidden="true">{en ? "M" : "م"}</span>
        {GROUPS.map((g) => {
          const items = sections.filter((x) => x.group === g.key);
          if (!items.length) return null;
          return (
            <div key={g.key} className="nav-group" role="group" aria-label={(en ? g.en : g.ar) || undefined}>
              {(en ? g.en : g.ar) && <span className="nav-title">{en ? g.en : g.ar}</span>}
              {items.map((x) => (
                <NavLink key={x.path} to={x.path} end={x.path === "/"}
                  className={({ isActive }) => (isActive || (x.path === "/rumors" && loc.pathname.startsWith("/claims")) ? "on" : "")}>
                  <span className="nav-ic"><Icon name={x.icon} /></span><span className="nav-tx">{en ? x.en : x.ar}</span>
                </NavLink>
              ))}
            </div>
          );
        })}
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
          <button className={`mode-btn${ap.hints ? " on" : ""}`} onClick={() => setAp({ hints: !ap.hints })} aria-pressed={ap.hints}
            aria-label={en ? "Hints" : "التلميحات"} title={ap.hints ? (en ? "Hide hints" : "إخفاء التلميحات") : (en ? "Show hints" : "إظهار التلميحات: شرح قصير لكل زر وعنوان عند الوقوف عليه")}><Icon name="hint" /></button>
          <button className="mode-btn" onClick={() => nav(`/help?topic=${intro?.[2] ?? "start"}`)} aria-label={en ? "Help for this screen" : "شرح هذه الشاشة"}
            title={en ? "Help for this screen" : "شرح هذه الشاشة من الدليل"}>؟</button>
          <button className="mode-btn" onClick={() => savePrefs({ theme: dark ? "light" : "dark", pattern: "c" })}
            title={dark ? (en ? "Switch to light" : "التبديل إلى الفاتح") : (en ? "Switch to dark" : "التبديل إلى الداكن")}
            aria-label={dark ? (en ? "Light mode" : "الوضع الفاتح") : (en ? "Dark mode" : "الوضع الداكن")}>{dark ? "☀" : "☾"}</button>
          <button className="av" title={en ? "My preferences" : "تفضيلاتي"} aria-label={en ? "My preferences" : "تفضيلاتي"}
            onClick={() => nav("/me")}>{(me.full_name || me.email).trim().charAt(0).toUpperCase()}</button>
        </header>
        <main className="body">
          {ap.hints && intro && <p className="page-intro">{intro[1]}</p>}
          <Outlet />
          <ReaderDrawer />
        </main>
      </div>
      <HintLayer on={ap.hints} />
      {tour && <Tour onClose={() => setTour(false)} />}
    </Frame>
  );
}
