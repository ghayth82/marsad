// النسخ الاحتياطي: باقات يختار فيها المدير ما يُنسخ ومكانه وموعده، واسترداد ما يختاره من أي نسخة.
import { useEffect, useState } from "react";
import { api } from "../../api";
import { Backups, tauri } from "./System";

type CatRow = { id: string; label: string; hint: string; rows?: number; files?: number; bytes?: number; needs?: string[] };
type Catalog = { db: CatRow[]; files: CatRow[]; not_included: string };
type Schedule = { kind: "manual" | "daily" | "weekly" | "monthly"; time: string; weekday: number; day: number };
type Pkg = {
  id: string; name: string; items: string[]; dest: string; dest_path: string; builtin?: boolean; schedule: Schedule; keep: number; encrypt: boolean; has_passphrase: boolean;
  last_status?: "ok" | "error" | "running"; last_run_at?: string; last_message?: string; last_file?: string; last_size?: number;
};
type Found = { path: string; name: string; size: number; created_at: string; package: string; encrypted: boolean };
type Inspect = { path: string; created_at: string; package: string; encrypted: boolean; same_device: boolean;
  contents: { id: string; label: string; rows?: number; files?: number; auto?: boolean }[] };

const DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"];
const size = (b = 0) => b >= 2 ** 30 ? `${(b / 2 ** 30).toFixed(1)} غ.ب` : b >= 2 ** 20 ? `${(b / 2 ** 20).toFixed(1)} م.ب` : b ? `${Math.max(1, Math.round(b / 1024))} ك.ب` : "فارغ";
const when = (s: Schedule) => s.kind === "manual" ? "يدوي فقط" : s.kind === "daily" ? `يوميًا ${s.time}` : s.kind === "weekly" ? `كل ${DAYS[s.weekday]} ${s.time}` : `يوم ${s.day} من كل شهر ${s.time}`;
const fmt = (iso?: string) => iso ? new Date(iso).toLocaleString("ar", { dateStyle: "medium", timeStyle: "short" }) : "";

const EMPTY = { name: "", items: [] as string[], dest: "", schedule: { kind: "daily", time: "03:00", weekday: 4, day: 1 } as Schedule, keep: 7, encrypt: true, passphrase: "" };

export function BackupPage() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [pkgs, setPkgs] = useState<Pkg[]>([]);
  const [edit, setEdit] = useState<(typeof EMPTY & { id?: string; has_passphrase?: boolean; builtin?: boolean }) | null>(null);
  const [msg, setMsg] = useState("");
  const load = () => api<Pkg[]>("/api/admin/backup/packages").then(setPkgs).catch((e) => setMsg(e.message));
  useEffect(() => { api<Catalog>("/api/admin/backup/catalog").then(setCat).catch((e) => setMsg(e.message)); load(); }, []);
  // ما دامت باقة تعمل نتابعها
  useEffect(() => {
    if (!pkgs.some((p) => p.last_status === "running")) return;
    const t = setTimeout(load, 2500);
    return () => clearTimeout(t);
  }, [pkgs]);

  const label = (id: string) => [...(cat?.db ?? []), ...(cat?.files ?? [])].find((x) => x.id === id)?.label ?? id;
  const run = async (p: Pkg) => { setMsg(""); await api(`/api/admin/backup/packages/${p.id}/run`, { method: "POST" }); load(); };
  const del = async (p: Pkg) => {
    if (!window.confirm(`حذف الباقة «${p.name}» من القائمة؟ النسخ التي أُخذت تبقى في مكانها على القرص.`)) return;
    await api(`/api/admin/backup/packages/${p.id}`, { method: "DELETE" }); load();
  };

  return (
    <div className="cols">
      <div className="grow">
        <section className="card" aria-label="باقات النسخ">
          <h2>باقات النسخ الاحتياطي</h2>
          <span className="mu">الباقة: ما تختاره من قاعدة البيانات والملفات، ومكان حفظه، وموعده. الملفات تُنسخ تراكميًا: كل نسخة تضيف الجديد فقط.</span>
          {msg && <div className="msg err" role="alert">{msg}</div>}
          {!pkgs.length && !edit && <div className="empty"><span>لا باقات بعد. أنشئ باقة لتنسخ ما تريد إلى قرص خارجي أو مجلد آخر.</span></div>}
          {pkgs.map((p) => (
            <div className="row" key={p.id} data-pkg={p.name}>
              <span className="f">
                <b>{p.name}</b> {p.builtin && <span className="pill p-ac">تلقائية</span>} {p.encrypt && <span className="pill p-n">مشفّرة</span>}<br />
                <span className="mu">{p.items.map(label).join("، ")}</span><br />
                <span className="mu">{when(p.schedule)} · تُحفظ آخر {p.keep} · {p.dest ? <code dir="ltr" style={{ fontSize: 12 }}>{p.dest}</code> : "مجلد «النسخ الاحتياطي»"}</span><br />
                {p.last_status === "running" && <span className="pill p-warn" role="status">تعمل الآن…</span>}
                {p.last_status === "ok" && <span className="pill p-ok" role="status">آخر نسخة {fmt(p.last_run_at)} · {p.last_message} · {size(p.last_size)}</span>}
                {p.last_status === "error" && <span className="pill p-bad" role="status">فشلت {fmt(p.last_run_at)}: {p.last_message}</span>}
              </span>
              <span style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <button className="btn sm pri" disabled={p.last_status === "running"} onClick={() => run(p)}>انسخ الآن</button>
                <button className="btn sm" onClick={() => setEdit({ ...EMPTY, ...p, passphrase: "" })}>تعديل</button>
                {!p.builtin && <button className="btn sm" onClick={() => del(p)}>حذف</button>}
              </span>
            </div>
          ))}
          {!edit && <div><button className="btn" onClick={() => setEdit({ ...EMPTY })}>باقة جديدة</button></div>}
          {edit && cat && <Editor value={edit} cat={cat} onCancel={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} />}
        </section>
        <Restore pkgs={pkgs} />
      </div>
      <div className="side"><Backups /></div>
    </div>
  );
}

function Checklist({ cat, picked, onChange, available }: { cat: { db: CatRow[]; files: CatRow[] }; picked: string[]; onChange: (v: string[]) => void; available?: Set<string> }) {
  const toggle = (id: string) => onChange(picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const auto = new Set(cat.db.filter((r) => picked.includes(r.id)).flatMap((r) => r.needs ?? []).filter((x) => !picked.includes(x)));
  const group = (title: string, rows: CatRow[], all: string[]) => !rows.some((r) => !available || available.has(r.id)) ? null : (
    <fieldset style={{ border: 0, padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4 }}>
      <legend><b>{title}</b> <button type="button" className="btn sm" onClick={() => onChange(Array.from(new Set([...picked, ...all])))}>الكل</button></legend>
      {rows.filter((r) => !available || available.has(r.id)).map((r) => (
        <label className="chk" key={r.id}>
          <input type="checkbox" checked={picked.includes(r.id)} onChange={() => toggle(r.id)} aria-label={`${title}: ${r.label}`} />
          <span><b>{r.label}</b>{auto.has(r.id) && <span className="pill p-n"> يُضاف تلقائيًا</span>}<br />
            <span className="mu">{[r.hint, r.rows !== undefined ? `${r.rows} سجل` : "", r.files !== undefined ? `${r.files} ملف` : "", r.bytes !== undefined ? size(r.bytes) : ""].filter(Boolean).join(" · ")}</span></span>
        </label>
      ))}
    </fieldset>
  );
  return (
    <div className="g2" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 12 }}>
      {group("قاعدة البيانات", cat.db, cat.db.map((r) => r.id))}
      {group("الملفات", cat.files, cat.files.map((r) => r.id))}
    </div>
  );
}

function Editor({ value, cat, onCancel, onSaved }: { value: typeof EMPTY & { id?: string; has_passphrase?: boolean; builtin?: boolean }; cat: Catalog; onCancel: () => void; onSaved: () => void }) {
  const [f, setF] = useState(value);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const s = f.schedule;
  const save = async (e: React.FormEvent) => {
    e.preventDefault(); setErr(""); setBusy(true);
    try {
      await api(f.id ? `/api/admin/backup/packages/${f.id}` : "/api/admin/backup/packages",
        { method: f.id ? "PUT" : "POST", body: { ...f, passphrase: f.passphrase || null } });
      onSaved();
    } catch (x) { setErr((x as Error).message); } finally { setBusy(false); }
  };
  return (
    <form onSubmit={save} className="card" style={{ background: "var(--sf2)", display: "flex", flexDirection: "column", gap: 10 }} aria-label="الباقة">
      <h3 style={{ margin: 0 }}>{f.id ? `تعديل «${value.name}»` : "باقة جديدة"}</h3>
      {f.builtin
        ? <span className="mu">تعمل وحدها من أول تشغيل. اختر ما يدخل فيها: قاعدة البيانات وحدها (الافتراضي)، أو معها الصور والوثائق والصفحات المؤرشفة. لا تُحذف؛ لإيقافها اجعل موعدها «يدوي فقط».</span>
        : <label className="fld">اسم الباقة<input className="inp" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="مثال: أسبوعي - كل شيء إلى القرص الخارجي" /></label>}
      <span><b>ماذا تنسخ؟</b> <span className="mu">ما يعتمد عليه اختيارك يُضاف تلقائيًا (الادّعاءات تحتاج الأخبار التي تشير إليها، وكل شيء يحتاج الحسابات).</span></span>
      <Checklist cat={cat} picked={f.items} onChange={(items) => setF({ ...f, items })} />
      <span className="mu" style={{ fontSize: 12 }}>لا يُنسخ: {cat.not_included}</span>
      <label className="fld">مكان الحفظ{f.builtin ? " (اتركه فارغًا: مجلد «النسخ الاحتياطي» في التخزين)" : ""}<input className="inp" dir="ltr" value={f.dest} onChange={(e) => setF({ ...f, dest: e.target.value })} placeholder="E:\" aria-label="مكان الحفظ" /></label>
      {tauri() && <div><button type="button" className="btn sm" onClick={async () => { const d = await tauri()!.core.invoke<string | null>("pick_folder"); if (d) setF({ ...f, dest: d }); }}>اختيار مجلد…</button></div>}
      <span className="mu" style={{ fontSize: 12 }}>تُحفظ في مجلد «مرصد التحقق - نسخ احتياطية / اسم الباقة» داخل المكان المختار. قرص خارجي هو الأفضل: يبقى لو تعطّل الجهاز.</span>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "end" }}>
        <label className="fld">الموعد
          <select className="inp" aria-label="الموعد" value={s.kind} onChange={(e) => setF({ ...f, schedule: { ...s, kind: e.target.value as Schedule["kind"] } })}>
            <option value="manual">يدوي فقط</option><option value="daily">يوميًا</option><option value="weekly">أسبوعيًا</option><option value="monthly">شهريًا</option>
          </select></label>
        {s.kind === "weekly" && <label className="fld">اليوم<select className="inp" aria-label="اليوم" value={s.weekday} onChange={(e) => setF({ ...f, schedule: { ...s, weekday: Number(e.target.value) } })}>{DAYS.map((d, i) => <option key={d} value={i}>{d}</option>)}</select></label>}
        {s.kind === "monthly" && <label className="fld">يوم الشهر<input className="inp" type="number" min={1} max={28} aria-label="يوم الشهر" value={s.day} onChange={(e) => setF({ ...f, schedule: { ...s, day: Number(e.target.value) } })} /></label>}
        {s.kind !== "manual" && <label className="fld">الساعة<input className="inp" type="time" aria-label="الساعة" value={s.time} onChange={(e) => setF({ ...f, schedule: { ...s, time: e.target.value } })} /></label>}
        <label className="fld">عدد النسخ المحفوظة<input className="inp" type="number" min={1} max={365} aria-label="عدد النسخ المحفوظة" value={f.keep} onChange={(e) => setF({ ...f, keep: Number(e.target.value) })} /></label>
      </div>
      <label className="chk"><input type="checkbox" aria-label="تشفير النسخ" checked={f.encrypt} onChange={(e) => setF({ ...f, encrypt: e.target.checked })} />
        تشفير النسخ بعبارة مرور (موصى به للقرص الخارجي: قد يضيع أو يُسرق)</label>
      {f.encrypt && <label className="fld">عبارة المرور{f.has_passphrase ? " (اتركها فارغة لإبقاء الحالية)" : ""}
        <input className="inp" type="password" aria-label="عبارة المرور" value={f.passphrase} onChange={(e) => setF({ ...f, passphrase: e.target.value })} placeholder="8 أحرف على الأقل" />
        <span className="mu" style={{ fontSize: 12 }}>احفظها في مكان آمن: بدونها لا تُفتح النسخ على جهاز آخر.</span></label>}
      {err && <div className="msg err" role="alert">{err}</div>}
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn pri" disabled={busy || !f.name.trim() || !f.items.length || (!f.builtin && !f.dest.trim())}
          data-why={!f.items.length ? "اختر شيئًا واحدًا على الأقل لنسخه" : !f.builtin && !f.dest.trim() ? "اختر مكان الحفظ" : !f.name.trim() ? "اكتب اسمًا للباقة" : undefined}>حفظ الباقة</button>
        <button type="button" className="btn" onClick={onCancel}>إلغاء</button>
      </div>
    </form>
  );
}

function Restore({ pkgs }: { pkgs: Pkg[] }) {
  const [folder, setFolder] = useState("");
  const [found, setFound] = useState<Found[] | null>(null);
  const [sel, setSel] = useState<Found | null>(null);
  const [pass, setPass] = useState("");
  const [info, setInfo] = useState<Inspect | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const dests = Array.from(new Set(pkgs.map((p) => p.dest_path)));
  const err = (x: unknown) => setMsg({ ok: false, text: (x as Error).message });

  const look = async (dir: string) => {
    setFolder(dir); setSel(null); setInfo(null); setMsg(null);
    try { setFound(await api<Found[]>("/api/admin/backup/list", { method: "POST", body: { folder: dir } })); } catch (x) { setFound(null); err(x); }
  };
  const open = async (b: Found, p = pass) => {
    setSel(b); setInfo(null); setMsg(null);
    if (b.encrypted && !p) return;
    try {
      const r = await api<Inspect>("/api/admin/backup/inspect", { method: "POST", body: { path: b.path, passphrase: p || null } });
      setInfo(r); setPicked(r.contents.filter((c) => !c.auto).map((c) => c.id));
    } catch (x) { err(x); }
  };
  const go = async () => {
    if (!info) return;
    const warn = mode === "replace"
      ? "«استبدل» يعيد الأقسام المختارة كما كانت في النسخة، ويحذف ما أُضيف بعدها وما يرتبط به. ستُؤخذ نسخة أمان من الوضع الحالي أولًا. هل تتابع؟"
      : "سيُعاد من النسخة ما ليس موجودًا الآن فقط، ولن يُمس ما تغيّر بعدها. ستُؤخذ نسخة أمان من الوضع الحالي أولًا. هل تتابع؟";
    if (!window.confirm(warn)) return;
    setBusy(true); setMsg(null);
    try {
      const r = await api<{ summary: { added: number; updated: number; removed: number; skipped: number; files: number }; safety_backup: string | null }>(
        "/api/admin/backup/restore", { method: "POST", body: { path: info.path, items: picked, mode, passphrase: pass || null } });
      const s = r.summary;
      setMsg({ ok: true, text: `تمّ الاسترداد: أُضيف ${s.added} سجل` + (mode === "replace" ? `، وحُدّث ${s.updated}، وحُذف ${s.removed}` : "")
        + (s.skipped ? `، وتُجووز ${s.skipped} لتعارضه مع بيانات أحدث` : "") + `، وأُعيد ${s.files} ملف.`
        + (r.safety_backup ? ` نسخة الأمان قبل الاسترداد في مجلد «النسخ الاحتياطي / قبل الاسترداد».` : "") });
    } catch (x) { err(x); } finally { setBusy(false); }
  };

  return (
    <section className="card" aria-label="الاسترداد">
      <h2>الاسترداد</h2>
      <span className="mu">اختر مكان النسخ، ثم النسخة، ثم ما تريد استرداده منها.</span>
      {!!dests.length && <div className="tabs">{dests.map((d) => <button key={d} type="button" className="btn sm" onClick={() => look(d)}><span dir="ltr">{d}</span></button>)}</div>}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input className="inp" dir="ltr" style={{ flex: 1, minWidth: 200 }} value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="E:\" aria-label="مكان النسخ" />
        {tauri() && <button type="button" className="btn sm" onClick={async () => { const d = await tauri()!.core.invoke<string | null>("pick_folder"); if (d) look(d); }}>اختيار مجلد…</button>}
        <button type="button" className="btn" disabled={!folder.trim()} data-why="اكتب مكان النسخ أو اختره" onClick={() => look(folder)}>اعرض النسخ</button>
      </div>
      {found && !found.length && <div className="empty"><span>لا نسخ في هذا المكان.</span></div>}
      {found?.map((b) => (
        <div className="row" key={b.path}>
          <span className="f"><b>{b.package}</b> · {fmt(b.created_at)} · {size(b.size)} {b.encrypted && <span className="pill p-n">مشفّرة</span>}</span>
          <button className="btn sm" aria-pressed={sel?.path === b.path} onClick={() => open(b)}>اختر</button>
        </div>
      ))}
      {sel?.encrypted && !info && (
        <form onSubmit={(e) => { e.preventDefault(); open(sel, pass); }} style={{ display: "flex", gap: 8 }}>
          <input className="inp" type="password" value={pass} onChange={(e) => setPass(e.target.value)} placeholder="عبارة مرور النسخة" aria-label="عبارة مرور النسخة" />
          <button className="btn" disabled={!pass}>افتح</button>
        </form>
      )}
      {info && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <h3 style={{ margin: 0 }}>ما في نسخة {fmt(info.created_at)}</h3>
          {!info.same_device && <div className="msg warn">هذه النسخة من جهاز آخر.{info.encrypted ? "" : " لأنها غير مشفّرة، تُسترد ملفاتها فقط؛ لنقل قاعدة البيانات بين الأجهزة استعمل «ملف النقل»."}</div>}
          <Checklist cat={{ db: info.contents.filter((c) => c.id.startsWith("db:")).map((c) => ({ ...c, hint: c.auto ? "أُضيف تلقائيًا للنسخة" : "" })),
            files: info.contents.filter((c) => c.id.startsWith("files:")).map((c) => ({ ...c, hint: "" })) }} picked={picked} onChange={setPicked} />
          <fieldset style={{ border: 0, padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 4 }}>
            <legend><b>طريقة الاسترداد</b></legend>
            <label className="chk"><input type="radio" name="mode" checked={mode === "merge"} onChange={() => setMode("merge")} />
              <span><b>أضف الناقص فقط (موصى به)</b><br /><span className="mu">يعيد ما حُذف، ولا يمس ما تغيّر أو أُضيف بعد النسخة.</span></span></label>
            <label className="chk"><input type="radio" name="mode" checked={mode === "replace"} onChange={() => setMode("replace")} />
              <span><b>استبدل</b><br /><span className="mu">يعيد الأقسام المختارة كما كانت تمامًا، ويضيع ما أُضيف بعد النسخة. الملفات لا تُحذف في الحالتين.</span></span></label>
          </fieldset>
          <div><button className="btn pri" disabled={busy || !picked.length} data-why="اختر ما تريد استرداده" onClick={go}>{busy ? "يجري الاسترداد…" : "استرد المختار"}</button></div>
        </div>
      )}
      {msg && <div className={`msg ${msg.ok ? "" : "err"}`} role="status">{msg.text}</div>}
    </section>
  );
}
