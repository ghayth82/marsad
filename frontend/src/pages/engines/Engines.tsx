import { useCallback, useEffect, useState } from "react";
import { Library, ProviderCard, type ProviderInfo } from "./Library";
import { NavLink, Route, Routes, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";
import { BatchView } from "./BatchView";
import type { EngineT, EnginesPayload } from "./types";
import { money, pct } from "./types";

const TASKS = [
  { key: "classify_verdict", name: "اقتراح حكم على ادّعاء" },
  { key: "extract_claims", name: "استخراج الادّعاءات" },
  { key: "summarize", name: "تلخيص مادة" },
];

export function Engines() {
  const can = useCan();
  const [data, setData] = useState<EnginesPayload | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api<EnginesPayload>("/api/engines").then(setData).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); }, [load]);
  if (err) return <div className="msg err">{err}</div>;
  if (!data) return null;
  return (
    <>
      <nav className="tabs" aria-label="أقسام المحركات">
        <NavLink to="/engines" end className={({ isActive }) => (isActive ? "on" : "")}>تشغيل ومقارنة</NavLink>
        <NavLink to="/engines/library" className={({ isActive }) => (isActive ? "on" : "")}>مكتبة المحركات</NavLink>
        {can("engines.manage") && <NavLink to="/engines/settings" className={({ isActive }) => (isActive ? "on" : "")}>الإعداد</NavLink>}
      </nav>
      <Notifications />
      <Routes>
        <Route index element={<RunPage data={data} />} />
        <Route path="batch/:id" element={<BatchRoute engines={data.engines} />} />
        <Route path="library" element={<Library reloadEngines={load} />} />
        {can("engines.manage") && <Route path="settings" element={<SettingsPage data={data} reload={load} />} />}
      </Routes>
    </>
  );
}

function BatchRoute({ engines }: { engines: EngineT[] }) {
  const { id } = useParams();
  return <BatchView key={id} id={Number(id)} engines={engines} />;
}

function Notifications() {
  const [rows, setRows] = useState<{ id: number; text: string }[]>([]);
  useEffect(() => { api<{ id: number; text: string }[]>("/api/engines/notifications").then(setRows).catch(() => {}); }, []);
  if (!rows.length) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.slice(0, 3).map((n) => (
        <div key={n.id} className="msg warn" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <span style={{ flex: 1 }}>{n.text}</span>
          <button className="btn sm" onClick={async () => { await api(`/api/engines/notifications/${n.id}/read`, { method: "POST" }); setRows(rows.filter((r) => r.id !== n.id)); }}>تم</button>
        </div>
      ))}
    </div>
  );
}

function RunPage({ data }: { data: EnginesPayload }) {
  const nav = useNavigate();
  const st = data.settings;
  const enabled = data.engines.filter((e) => e.enabled);
  const [task, setTask] = useState("classify_verdict");
  const [claim, setClaim] = useState("");
  const [text, setText] = useState("");
  const [mode, setMode] = useState<"single" | "multi">(st.mode);
  const [picked, setPicked] = useState<number[]>(st.mode === "multi" ? st.multi_engine_ids : st.default_engine_id ? [st.default_engine_id] : []);
  const [mergeId, setMergeId] = useState<number | "">(st.merge_engine_id ?? "");
  const [est, setEst] = useState<{ max_total_usd: number; engines: { name: string; max_cost_usd: number | null; would_exceed: boolean }[] } | null>(null);
  const [err, setErr] = useState("");
  const [recent, setRecent] = useState<{ id: number; task_name: string; preview: string; status: string; created_at: string; mode: string }[]>([]);
  useEffect(() => { api<typeof recent>("/api/engines/batches").then(setRecent).catch(() => {}); }, []);

  const body = () => ({
    task, input: task === "classify_verdict" ? { claim, text } : { text }, mode,
    engine_ids: mode === "single" ? picked.slice(0, 1) : picked, merge_engine_id: mode === "multi" && mergeId ? mergeId : null,
  });
  const toggle = (id: number) => setPicked(mode === "single" ? [id] : picked.includes(id) ? picked.filter((x) => x !== id) : [...picked, id]);
  const go = async () => {
    setErr("");
    try { const r = await api<{ batch_id: number }>("/api/engines/runs", { method: "POST", body: body() }); nav(`/engines/batch/${r.batch_id}`); }
    catch (e) { setErr((e as Error).message); }
  };

  if (!enabled.length) return <section className="card"><h2>لا توجد محركات بعد</h2><span className="mu">يضيف المدير المحركات من «الإعداد».</span></section>;

  return (
    <div className="cols">
      <div className="grow">
        <section className="card">
          <h2>تشغيل مهمة</h2>
          <label className="fld">المهمة
            <select className="inp" value={task} onChange={(e) => setTask(e.target.value)}>{TASKS.map((t) => <option key={t.key} value={t.key}>{t.name}</option>)}</select>
          </label>
          {task === "classify_verdict" && <label className="fld">الادّعاء<input className="inp" value={claim} onChange={(e) => setClaim(e.target.value)} /></label>}
          <label className="fld">{task === "classify_verdict" ? "النص أو الأدلة المتاحة" : "النص"}
            <textarea className="inp" rows={6} style={{ height: "auto", padding: 10, lineHeight: 1.8 }} value={text} onChange={(e) => setText(e.target.value)} />
          </label>
          <div className="seg" role="group" aria-label="وضع التشغيل">
            <button className={mode === "single" ? "on" : ""} aria-pressed={mode === "single"} onClick={() => { setMode("single"); setPicked(picked.slice(0, 1)); }}>محرك واحد</button>
            <button className={mode === "multi" ? "on" : ""} aria-pressed={mode === "multi"} onClick={() => setMode("multi")}>عدة محركات + دمج</button>
          </div>
          <fieldset style={{ border: "none", padding: 0, margin: 0 }}>
            <legend className="mu">{mode === "single" ? "المحرك" : "المحركات (اثنان أو أكثر)"}</legend>
            <div className="tabs">
              {enabled.map((e) => (
                <label key={e.id} className="chk"><input type={mode === "single" ? "radio" : "checkbox"} name="eng" checked={picked.includes(e.id)} onChange={() => toggle(e.id)} />
                  {e.name} {e.local ? <span className="pill p-ok">محلي</span> : null}</label>
              ))}
            </div>
          </fieldset>
          {mode === "multi" && (
            <label className="fld">محرك الدمج
              <select className="inp" value={mergeId} onChange={(e) => setMergeId(e.target.value ? Number(e.target.value) : "")}>
                <option value="">دون دمج (مقارنة فقط)</option>{enabled.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select>
            </label>
          )}
          {est && (
            <div className={`msg ${est.engines.some((x) => x.would_exceed) ? "err" : "ok"}`}>
              الكلفة القصوى المقدّرة: {money(est.max_total_usd)}
              {est.engines.filter((x) => x.would_exceed).map((x) => <div key={x.name}>«{x.name}» سيتجاوز حد إنفاقه ولن يعمل.</div>)}
            </div>
          )}
          {err && <div className="msg err">{err}</div>}
          <div className="tabs">
            {mode === "multi" && <button className="btn" onClick={async () => { try { setEst(await api("/api/engines/estimate", { method: "POST", body: body() })); } catch (e) { setErr((e as Error).message); } }}>تقدير الكلفة</button>}
            <button className="btn pri" disabled={!picked.length || (mode === "multi" && picked.length < 2) || !(text.trim() || claim.trim())} onClick={go}>تشغيل</button>
          </div>
        </section>
      </div>
      <div className="side">
        <section className="card">
          <h2>آخر التشغيلات</h2>
          {!recent.length && <span className="mu">لا شيء بعد.</span>}
          {recent.map((r) => (
            <div key={r.id} className="row">
              <span className="f"><a href={`/engines/batch/${r.id}`} onClick={(e) => { e.preventDefault(); nav(`/engines/batch/${r.id}`); }}>{r.preview || r.task_name}</a><br />
                <span className="mu">{r.task_name} · {r.mode === "multi" ? "عدة محركات" : "محرك واحد"}</span></span>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

const PRESETS: Record<string, { provider: string; name: string; model: string; base_url?: string; price_in?: number; price_out?: number; note?: string }> = {
  claude: { provider: "anthropic", name: "Claude Haiku", model: "", price_in: 0.1, price_out: 0.5, note: "السعر المقترح لـ Haiku من صفحة أسعار Claude في الخطة؛ تحقق منه، فالمزوّدون لا يرسلون الأسعار مع قائمة النماذج." },
  gemini: { provider: "gemini", name: "Gemini Flash", model: "", note: "انتبه: الطبقة المجانية من Gemini قد تستخدم الطلبات لتحسين منتجات Google. لا ترسل عبرها وثائق حساسة." },
  openai: { provider: "openai", name: "OpenAI", model: "" },
  ollama: { provider: "ollama", name: "Qwen محلي", model: "", base_url: "http://127.0.0.1:11434/v1", note: "يعمل على جهازك عبر Ollama؛ النص لا يغادر الجهاز. شغّل Ollama ثم اجلب النماذج المحمّلة فيه." },
  compatible: { provider: "openai_compatible", name: "", model: "", base_url: "" },
};
type Draft = { id?: number; name: string; provider: string; model: string; base_url: string; api_key: string; price_in: string; price_out: string; monthly_limit_usd: string; enabled: boolean; note?: string };
const emptyDraft: Draft = { name: "", provider: "anthropic", model: "", base_url: "", api_key: "", price_in: "", price_out: "", monthly_limit_usd: "", enabled: true };

function SettingsPage({ data, reload }: { data: EnginesPayload; reload: () => Promise<void> }) {
  const [params] = useSearchParams();
  const [info, setInfo] = useState<Record<string, ProviderInfo>>({});
  useEffect(() => { api<{ providers: Record<string, ProviderInfo> }>("/api/engines/catalog").then((c) => setInfo(c.providers)).catch(() => {}); }, []);
  const st = data.settings;
  const [draft, setDraft] = useState<Draft | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [tests, setTests] = useState<Record<number, string>>({});
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  const [modelsErr, setModelsErr] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);
  const openDraft = (d: Draft | null) => { setDraft(d); setModels([]); setModelsErr(""); };
  // «أضف هذا المحرك» من المكتبة يفتح النموذج مملوءًا بالمزوّد المختار
  const preset = params.get("preset");
  useEffect(() => {
    const p = preset ? PRESETS[preset] : undefined;
    if (p) setDraft({ ...emptyDraft, ...p, base_url: p.base_url ?? "", price_in: p.price_in?.toString() ?? "", price_out: p.price_out?.toString() ?? "" });
  }, [preset]);
  const fetchModels = async () => {
    if (!draft) return;
    setModelsErr(""); setLoadingModels(true);
    try {
      const r = await api<{ models: { id: string; label: string }[] }>("/api/engines/models", { method: "POST",
        body: { provider: draft.provider, api_key: draft.api_key || null, base_url: draft.base_url, engine_id: draft.id ?? null } });
      setModels(r.models);
      if (!draft.model && r.models.length) setDraft({ ...draft, model: r.models[0].id });
    } catch (e) { setModelsErr((e as Error).message); setModels([]); }
    finally { setLoadingModels(false); }
  };
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); await reload(); setMsg({ kind: "ok", text: ok }); } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const save = (c: Partial<typeof st>) => run(() => api("/api/engines/settings/current", { method: "PUT", body: c }), "حُفظ الإعداد.");
  const role = (e: EngineT) => [
    st.mode === "single" && st.default_engine_id === e.id && "الافتراضي",
    st.mode === "multi" && st.multi_engine_ids.includes(e.id) && "مشارك",
    st.merge_engine_id === e.id && "الدمج",
  ].filter(Boolean).join(" + ") || "—";
  const numOrNull = (s: string) => (s.trim() === "" ? null : Number(s));
  const submit = () => draft && run(async () => {
    const body = { name: draft.name, provider: draft.provider, model: draft.model, base_url: draft.base_url, enabled: draft.enabled,
      price_in: numOrNull(draft.price_in), price_out: numOrNull(draft.price_out), monthly_limit_usd: numOrNull(draft.monthly_limit_usd),
      ...(draft.api_key ? { api_key: draft.api_key } : {}) };
    await api(draft.id ? `/api/engines/${draft.id}` : "/api/engines", { method: draft.id ? "PUT" : "POST", body });
    openDraft(null);
  }, "حُفظ المحرك. المفتاح محفوظ مشفّرًا ولا يظهر مرة أخرى.");

  return (
    <div className="cols">
      <div className="grow">
        {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}
        <section className="card">
          <h2>وضع التشغيل</h2>
          <div className="seg" role="group" aria-label="الوضع الافتراضي">
            <button className={st.mode === "single" ? "on" : ""} aria-pressed={st.mode === "single"} onClick={() => save({ mode: "single" })}>محرك واحد</button>
            <button className={st.mode === "multi" ? "on" : ""} aria-pressed={st.mode === "multi"} onClick={() => save({ mode: "multi" })}>عدة محركات لكل المهام + محرك دمج</button>
          </div>
          <span className="mu">كل محرك ينفّذ كل المهام وله مخرج كامل. محرك الدمج يقترح مخرجًا واحدًا. أي خلاف، صغيرًا أو كبيرًا، يُعرض عليك والقرار لك.</span>
        </section>
        <section className="card">
          <h2>المحركات</h2>
          <div className="tw"><table>
            <thead><tr><th>المحرك</th><th>النوع</th><th>الحالة</th><th>الكلفة هذا الشهر</th><th>اتفاق قراراته مع قراراتكم</th><th>دوره</th><th></th></tr></thead>
            <tbody>{data.engines.map((e) => (
              <tr key={e.id}>
                <td><b>{e.name}</b><br /><span className="mu" dir="ltr">{e.model}</span></td>
                <td>{e.local ? "محلي · مجاني" : "سحابي"}</td>
                <td>{!e.enabled ? <span className="pill p-n">معطّل</span> : !e.local && !e.has_key ? <span className="pill p-warn">بلا مفتاح</span> : <span className="pill p-ok">جاهز</span>}
                  {tests[e.id] && <><br /><span className="mu">{tests[e.id]}</span></>}</td>
                <td>{e.local ? "0 $" : `${money(e.spent_usd)} / ${money(e.effective_limit_usd)}`}</td>
                <td>{pct(e.agreement)}{e.decisions ? <span className="mu"> ({e.decisions})</span> : null}</td>
                <td>{role(e)}</td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <button className="btn sm" onClick={() => openDraft({ id: e.id, name: e.name, provider: e.provider, model: e.model, base_url: e.base_url, api_key: "", price_in: e.price_in?.toString() ?? "", price_out: e.price_out?.toString() ?? "", monthly_limit_usd: e.monthly_limit_usd?.toString() ?? "", enabled: e.enabled })}>تعديل</button>{" "}
                  <button className="btn sm" onClick={async () => { const r = await api<{ ok: boolean; error?: string; model_version?: string }>(`/api/engines/${e.id}/test`, { method: "POST" }); setTests({ ...tests, [e.id]: r.ok ? `يعمل · ${r.model_version}` : r.error ?? "فشل" }); }}>اختبار</button>
                </td>
              </tr>))}
            </tbody>
          </table></div>
        </section>
        <section className="card">
          <h2>الأدوار</h2>
          <div className="g4">
            <label className="fld">المحرك الافتراضي (وضع المحرك الواحد)
              <select className="inp" value={st.default_engine_id ?? ""} onChange={(e) => save({ default_engine_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">—</option>{data.engines.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select></label>
            <label className="fld">محرك الدمج
              <select className="inp" value={st.merge_engine_id ?? ""} onChange={(e) => save({ merge_engine_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">دون دمج</option>{data.engines.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
              </select></label>
            <label className="fld">حد الإنفاق الافتراضي لكل محرك مدفوع ($ شهريًا)
              <input className="inp" type="number" min={0} step="1" defaultValue={st.default_limit_usd} onBlur={(e) => save({ default_limit_usd: Number(e.target.value) })} /></label>
          </div>
          <fieldset style={{ border: "none", padding: 0, margin: 0 }}><legend className="mu">المحركات المشاركة في وضع المحركات المتعددة</legend>
            <div className="tabs">{data.engines.map((e) => (
              <label key={e.id} className="chk"><input type="checkbox" checked={st.multi_engine_ids.includes(e.id)}
                onChange={(x) => save({ multi_engine_ids: x.target.checked ? [...st.multi_engine_ids, e.id] : st.multi_engine_ids.filter((i) => i !== e.id) })} />{e.name}</label>
            ))}</div>
          </fieldset>
          <span className="mu">عند بلوغ الحد يتوقف المحرك المدفوع ويصلك تنبيه، وتستمر المحركات المحلية.</span>
        </section>
        {!!data.accuracy.length && (
          <section className="card">
            <h2>دقة المحركات حسب المهمة</h2>
            <span className="mu">محسوبة من قراراتكم، للاستئناس لا للقرار.</span>
            <div className="tw"><table><thead><tr><th>المحرك</th><th>المهمة</th><th>الاتفاق</th><th>العدد</th></tr></thead>
              <tbody>{data.accuracy.map((a, i) => <tr key={i}><td>{a.engine}</td><td>{a.task_name}</td><td>{pct(a.rate)}</td><td>{a.total}</td></tr>)}</tbody></table></div>
          </section>
        )}
      </div>
      <div className="side">
        <section className="card">
          <h2>{draft?.id ? "تعديل محرك" : "إضافة محرك"}</h2>
          {!draft ? (<>
            <span className="mu">قبل الاختيار: «مكتبة المحركات» تشرح كل محرك ومتطلباته وكلفته، وفيها النماذج المحلية المجانية.</span>
            <div className="tabs">
              {Object.entries({ claude: "Claude", gemini: "Gemini", openai: "OpenAI", ollama: "محلي (Ollama)", compatible: "مزوّد متوافق" }).map(([k, l]) => (
                <button key={k} className="btn sm" onClick={() => { const p = PRESETS[k]; openDraft({ ...emptyDraft, ...p, base_url: p.base_url ?? "", price_in: p.price_in?.toString() ?? "", price_out: p.price_out?.toString() ?? "" }); }}>{l}</button>
              ))}
            </div></>
          ) : (
            <form onSubmit={(e) => { e.preventDefault(); submit(); }} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
              {info[draft.provider] && !draft.id && <ProviderCard p={info[draft.provider]} compact />}
              {draft.note && <div className="msg warn">{draft.note}</div>}
              <label className="fld">الاسم<input className="inp" required value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
              {(draft.provider === "openai_compatible" || draft.provider === "ollama") && (
                <label className="fld">العنوان<input className="inp" dir="ltr" required value={draft.base_url} onChange={(e) => setDraft({ ...draft, base_url: e.target.value })} placeholder="https://…/v1" /></label>
              )}
              {draft.provider !== "ollama" && (
                <label className="fld">المفتاح {draft.id && <span className="mu">(اتركه فارغًا لإبقاء الحالي)</span>}
                  <input className="inp" type="password" dir="ltr" autoComplete="off" value={draft.api_key} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} /></label>
              )}
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <button type="button" className="btn sm" disabled={loadingModels || (draft.provider !== "ollama" && !draft.api_key && !draft.id)} onClick={fetchModels}>
                  {loadingModels ? "جارٍ الجلب…" : "جلب النماذج من المزوّد"}
                </button>
                {modelsErr && <div className="msg err">{modelsErr}</div>}
                {models.length > 0 ? (
                  <label className="fld">النموذج ({models.length})
                    <select className="inp" dir="ltr" value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })}>
                      {!models.some((m) => m.id === draft.model) && draft.model && <option value={draft.model}>{draft.model}</option>}
                      {models.map((m) => <option key={m.id} value={m.id}>{m.label === m.id ? m.id : `${m.label} — ${m.id}`}</option>)}
                    </select>
                  </label>
                ) : (
                  <label className="fld">اسم النموذج <span className="mu">اجلبه من المزوّد أو اكتبه</span>
                    <input className="inp" dir="ltr" required value={draft.model} onChange={(e) => setDraft({ ...draft, model: e.target.value })} /></label>
                )}
              </div>
              {draft.provider !== "ollama" && (
                <div className="g4" style={{ gridTemplateColumns: "1fr 1fr" }}>
                  <label className="fld">سعر المُدخل ($ لكل مليون رمز)<input className="inp" type="number" min={0} step="any" value={draft.price_in} onChange={(e) => setDraft({ ...draft, price_in: e.target.value })} /></label>
                  <label className="fld">سعر الناتج<input className="inp" type="number" min={0} step="any" value={draft.price_out} onChange={(e) => setDraft({ ...draft, price_out: e.target.value })} /></label>
                </div>
              )}
              {draft.provider !== "ollama" && <label className="fld">حد الإنفاق الشهري ($) <span className="mu">فارغ = الافتراضي</span><input className="inp" type="number" min={0} step="any" value={draft.monthly_limit_usd} onChange={(e) => setDraft({ ...draft, monthly_limit_usd: e.target.value })} /></label>}
              <label className="chk"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} />مفعّل</label>
              <div className="tabs">
                <button className="btn pri">حفظ</button>
                <button type="button" className="btn" onClick={() => openDraft(null)}>إلغاء</button>
                {draft.id && <button type="button" className="btn danger" onClick={() => run(async () => { await api(`/api/engines/${draft.id}`, { method: "DELETE" }); openDraft(null); }, "حُذف المحرك.")}>حذف</button>}
              </div>
            </form>
          )}
          <span className="mu">المفاتيح تُحفظ مشفّرة، ولا تُكتب في أي محادثة.</span>
        </section>
      </div>
    </div>
  );
}
