// مكتبة المحركات: كل ما تحتاج معرفته قبل الاختيار أو التفعيل — للمحلية المجانية وللمدفوعة.
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../../api";
import { useCan } from "../../session";

export type ProviderInfo = {
  title: string; what: string; needs: string[]; cost: string; privacy: string; internet: string; quality: string;
  key_url: string; pricing_url: string; docs_url: string;
};
type Fit = { level: "fast" | "ok" | "heavy"; text: string; disk_ok: boolean };
type Local = {
  id: string; name: string; family: string; params: string; tier: string; size_gb: number; ram_gb: number; vram_gb: number;
  context: number; license: string; license_note: string; languages: string; arabic: string; strengths: string; limits: string;
  source: string; mirror: string; mirrored: boolean; installed: boolean; loaded: boolean; engine_id: number | null; fit: Fit;
  download: { status?: string; done?: number; total?: number; error?: string };
};
type HW = { ram_gb: number; vram_gb: number; gpus: { name: string; vram_gb: number }[]; disk_free_gb: number; cores: number; os: string; runtime: boolean };
export type Catalog = { hardware: HW; providers: Record<string, ProviderInfo>; local: Local[] };

const FIT_CLS = { fast: "p-ok", ok: "p-warn", heavy: "p-bad" } as const;
const FIT_WORD = { fast: "سريع على جهازك", ok: "يعمل على جهازك (أبطأ)", heavy: "ثقيل على جهازك" } as const;
const PAID = ["anthropic", "openai", "gemini", "openai_compatible", "ollama"] as const;
const PRESET_OF: Record<string, string> = { anthropic: "claude", openai: "openai", gemini: "gemini", openai_compatible: "compatible", ollama: "ollama" };

/** بطاقة تعريف المزوّد: ما هو، وما يحتاجه، وكلفته، وخصوصيته. تُعرض في المكتبة وفي نموذج الإضافة. */
export function ProviderCard({ p, compact }: { p: ProviderInfo; compact?: boolean }) {
  return (
    <div className="eng-card" style={compact ? { background: "var(--sf2)" } : undefined}>
      {!compact && <h3 style={{ margin: 0 }}>{p.title}</h3>}
      <span>{p.what}</span>
      <dl className="eng-facts">
        <dt>تحتاج</dt><dd><ul style={{ margin: 0, paddingInlineStart: 18 }}>{p.needs.map((n) => <li key={n}>{n}</li>)}</ul></dd>
        <dt>الكلفة</dt><dd>{p.cost}</dd>
        <dt>الخصوصية</dt><dd>{p.privacy}</dd>
        <dt>الإنترنت</dt><dd>{p.internet}</dd>
        <dt>الجودة</dt><dd>{p.quality}</dd>
      </dl>
      <span className="mu" style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        {p.key_url && <a href={p.key_url} target="_blank" rel="noreferrer">صفحة المفتاح ↗</a>}
        {p.pricing_url && <a href={p.pricing_url} target="_blank" rel="noreferrer">الأسعار الحالية ↗</a>}
        {p.docs_url && <a href={p.docs_url} target="_blank" rel="noreferrer">التوثيق ↗</a>}
      </span>
    </div>
  );
}

const gb = (b?: number) => ((b ?? 0) / 2 ** 30).toFixed(1);

export function Library({ reloadEngines }: { reloadEngines: () => Promise<void> | void }) {
  const [c, setC] = useState<Catalog | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [tier, setTier] = useState("");
  const nav = useNavigate();
  const manage = useCan()("engines.manage");
  const load = useCallback((refresh = false) => api<Catalog>(`/api/engines/catalog${refresh ? "?refresh=true" : ""}`).then(setC).catch((e) => setMsg({ kind: "err", text: e.message })), []);
  useEffect(() => { load(); }, [load]);
  const busy = c?.local.some((m) => ["downloading", "verifying"].includes(m.download.status ?? "")) ?? false;
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(() => load(), 1500);
    return () => clearInterval(t);
  }, [busy, load]);
  if (!c) return msg ? <div className="msg err">{msg.text}</div> : null;
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try { await fn(); setMsg({ kind: "ok", text: ok }); await load(); await reloadEngines(); } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const hw = c.hardware;
  const tiers = [...new Set(c.local.map((m) => m.tier))];
  return (
    <div className="cols">
      <div className="grow">
        {msg && <div className={`msg ${msg.kind}`} role="status">{msg.text}</div>}

        <section className="card" aria-labelledby="loc-h">
          <h2 id="loc-h">النماذج المحلية المجانية</h2>
          <ProviderCard p={c.providers.local} compact />
          {!hw.runtime && <div className="msg warn">المحرك المحلي (llama.cpp) غير مضمّن في هذه النسخة: يمكنك تنزيل النماذج، وتعمل في نسخة ويندوز المثبّتة أو على خادم فيه llama-server.</div>}
          <div className="seg" role="group" aria-label="الحجم">
            <button className={tier === "" ? "on" : ""} onClick={() => setTier("")}>الكل</button>
            {tiers.map((t) => <button key={t} className={tier === t ? "on" : ""} onClick={() => setTier(t)}>{t}</button>)}
          </div>
          <div className="eng-grid">
            {c.local.filter((m) => !tier || m.tier === tier).map((m) => {
              const d = m.download;
              const downloading = d.status === "downloading" || d.status === "verifying";
              return (
                <article key={m.id} className="eng-card" aria-label={m.name}>
                  <div style={{ display: "flex", gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                    <h3 style={{ margin: 0 }}>{m.name}</h3>
                    <span className="pill p-n">{m.tier}</span>
                    {m.loaded && <span className="pill p-ok">محمّل الآن</span>}
                    {m.engine_id && <span className="pill p-ok">مفعَّل</span>}
                  </div>
                  <span className="mu">{m.family} · {m.params}</span>
                  <span>{m.strengths}</span>
                  <dl className="eng-facts">
                    <dt>الحجم</dt><dd>{m.size_gb} غيغابايت على القرص</dd>
                    <dt>الذاكرة</dt><dd>نحو {m.ram_gb} غيغابايت، أو بطاقة رسوم بذاكرة {m.vram_gb} غيغابايت للسرعة</dd>
                    <dt>اللغات</dt><dd>{m.languages}</dd>
                    <dt>العربية</dt><dd>{m.arabic}</dd>
                    <dt>السياق</dt><dd>نحو {Math.round(m.context / 1000)} ألف رمز {m.context < 8000 ? "(قصير: لا يناسب الوثائق الطويلة)" : ""}</dd>
                    <dt>الترخيص</dt><dd>{m.license}{m.license_note ? ` — ${m.license_note}` : ""}</dd>
                    <dt>حدوده</dt><dd>{m.limits}</dd>
                  </dl>
                  <span className={`pill ${FIT_CLS[m.fit.level]}`} title={m.fit.text}>{FIT_WORD[m.fit.level]}</span>
                  <span className="mu">{m.fit.text}. للمعلومة فقط: يمكنك تنزيله على أي جهاز.</span>
                  {downloading && (
                    <div>
                      <progress max={d.total} value={d.done} style={{ width: "100%" }} aria-label={`تنزيل ${m.name}`} />
                      <span className="mu">{d.status === "verifying" ? "يُتحقق من البصمة…" : `${gb(d.done)} من ${gb(d.total)} غيغابايت`}</span>
                    </div>
                  )}
                  {d.status === "error" && <div className="msg err">{d.error}</div>}
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    {!manage ? <span className="mu">{m.installed ? "منزَّل على الجهاز." : "التنزيل والتفعيل لمدير المحركات."}</span> : !m.mirrored ? <span className="mu">لم يُنسخ إلى حسابك على Hugging Face بعد.</span>
                      : downloading ? <button className="btn sm" onClick={() => act(() => api(`/api/engines/local/${m.id}/cancel`, { method: "POST" }), "أُلغي التنزيل؛ يُستأنف من حيث توقف إن نزّلته من جديد.")}>إلغاء</button>
                      : !m.installed ? <button className="btn sm pri" onClick={() => act(() => api(`/api/engines/local/${m.id}/download`, { method: "POST" }), `بدأ تنزيل ${m.name} من نسختك على Hugging Face.`)}>تنزيل ({m.size_gb} غيغابايت)</button>
                      : <>
                        {!m.engine_id && <button className="btn sm pri" onClick={() => act(() => api(`/api/engines/local/${m.id}/activate`, { method: "POST" }), `${m.name} صار محركًا تختاره في «تشغيل ومقارنة» وفي الأدوار.`)}>تفعيل</button>}
                        {m.engine_id && <button className="btn sm" onClick={() => nav("/engines/settings")}>اختر دوره</button>}
                        <button className="btn sm" onClick={() => { if (confirm(`حذف ملف ${m.name} من القرص (${m.size_gb} غيغابايت)؟ يبقى في القائمة لتنزّله متى شئت.`)) act(() => api(`/api/engines/local/${m.id}`, { method: "DELETE" }), "حُذف الملف وتحررت المساحة."); }}>حذف من القرص</button>
                      </>}
                    <a className="mu" href={`https://huggingface.co/${m.mirror}`} target="_blank" rel="noreferrer">نسختك ↗</a>
                  </div>
                </article>
              );
            })}
          </div>
          <span className="mu">نموذج واحد يبقى محمّلًا في الذاكرة. اختيار نموذج آخر لمهمة يُنزل الأول ويحمّل الثاني وحده (قد يأخذ دقيقة).
            {" "}{manage && <button className="linkish" onClick={() => act(() => api("/api/engines/local/unload", { method: "POST" }), "أُفرغت الذاكرة.")}>إفراغ الذاكرة الآن</button>}</span>
        </section>

        <section className="card" aria-labelledby="paid-h">
          <h2 id="paid-h">المحركات المدفوعة والسحابية</h2>
          <span className="mu">أسماء النماذج تُجلب حيّة من المزوّد بمفتاحك عند الإضافة، والأسعار من صفحته لأنها تتغير؛ تُدخل السعر في المحرك ليحسب البرنامج الكلفة ويوقف الإنفاق عند حدّك.</span>
          <div className="eng-grid">
            {PAID.map((k) => (
              <div key={k} style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                <ProviderCard p={c.providers[k]} />
                {manage && <button className="btn sm" onClick={() => nav(`/engines/settings?preset=${PRESET_OF[k]}`)}>أضف هذا المحرك</button>}
              </div>
            ))}
          </div>
        </section>
      </div>

      <div className="side">
        <section className="card" aria-labelledby="hw-h">
          <h2 id="hw-h">جهازك</h2>
          <dl className="eng-facts">
            <dt>الذاكرة</dt><dd>{hw.ram_gb} غيغابايت</dd>
            <dt>بطاقة الرسوم</dt><dd>{hw.gpus.length ? hw.gpus.map((g) => `${g.name}${g.vram_gb ? ` (${g.vram_gb} غيغابايت)` : ""}`).join("، ") : "لم تُكتشف"}</dd>
            <dt>المعالج</dt><dd>{hw.cores} نواة</dd>
            <dt>مساحة النماذج</dt><dd>{hw.disk_free_gb} غيغابايت حرة</dd>
          </dl>
          <span className="mu">تُستعمل لعلامة «سريع/يعمل/ثقيل» فقط. على جهاز أقوى تتغير العلامات تلقائيًا.</span>
          <button className="btn sm" onClick={() => load(true)}>أعد فحص الجهاز</button>
        </section>
      </div>
    </div>
  );
}
