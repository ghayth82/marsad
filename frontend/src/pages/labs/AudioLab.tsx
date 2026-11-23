// الشاشة 8: مختبر الصوت.
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, apiForm } from "../../api";
import { Checks, fileUrl, fmt, gradePill, gradeText, mmss, type Media, type Recent, UploadForm, Verdict } from "./common";

type Cmp = { similarity: number; offset_s: number; verdict: string; grade: string };

export function AudioLab() {
  const { id } = useParams();
  const nav = useNavigate();
  const [m, setM] = useState<Media | null>(null);
  const [recent, setRecent] = useState<Recent[]>([]);
  const [other, setOther] = useState("");
  const [cmp, setCmp] = useState<Cmp | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Recent[]>("/api/labs/media?kind=audio").then(setRecent).catch(() => {}); }, [m?.id]);
  useEffect(() => { setCmp(null); if (id) api<Media>(`/api/labs/media/${id}`).then(setM).catch(() => setM(null)); else setM(null); }, [id]);
  const splice = m?.checks.find((c) => c.check === "splice");
  const tr = m?.checks.find((c) => c.check === "transcript");
  const compare = async () => {
    setErr("");
    const f = new FormData(); f.append("a", String(m!.id)); f.append("b", other);
    try { setCmp(await apiForm<Cmp>("/api/labs/audio/compare", f)); } catch (x) { setErr((x as Error).message); }
  };
  const peaks: number[] = splice?.result.peaks ?? [];
  const max = Math.max(0.01, ...peaks);

  return (
    <div className="cols">
      <div className="grow">
        {!m && <UploadForm accept="audio/*,video/*" label="افحص تسجيلًا صوتيًا" onDone={(x) => nav(`/audio-lab/${x.id}`)} />}
        {m && (
          <>
            <section className="card">
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <h2 style={{ flex: 1 }}>{m.filename || "تسجيل"}</h2>
                <button className="btn sm" onClick={() => nav("/audio-lab")}>تسجيل جديد</button>
              </div>
              <svg viewBox={`0 0 ${peaks.length * 3} 60`} preserveAspectRatio="none" style={{ width: "100%", height: 80 }} role="img" aria-label="موجة الصوت">
                {peaks.map((p, i) => <rect key={i} x={i * 3} y={30 - (p / max) * 28} width={2} height={Math.max(1, (p / max) * 56)} fill="var(--ac)" />)}
                {(splice?.result.points ?? []).map((p: { t: number }) => (
                  <rect key={p.t} x={(p.t / Math.max(m.duration, 0.1)) * peaks.length * 3} y={0} width={2.5} height={60} fill="var(--bad)" />
                ))}
              </svg>
              {(splice?.result.points ?? []).map((p: { t: number; reason: string }) => (
                <div key={p.t} className="mu" style={{ fontSize: 12 }}><span style={{ color: "var(--bad)" }}>■</span> نقطة قص محتملة عند {mmss(p.t)} ({p.reason})</div>
              ))}
              <audio src={fileUrl(m.sha256)} controls style={{ width: "100%" }} />
              <p className="mu" style={{ fontSize: 12 }}>{mmss(m.duration)} · البصمة <span dir="ltr">{m.sha256.slice(0, 4)}…{m.sha256.slice(-3)}</span> · أُرشف {fmt(m.seen_at)}</p>
            </section>
            <section className="card">
              <h2>التفريغ بمحركات «صوتي»</h2>
              {tr?.result.segments?.length ? tr.result.segments.map((s: { start: number; speaker: string; text: string }, i: number) => (
                <div key={i} className="row"><span className="mu" dir="ltr" style={{ width: 44 }}>{mmss(s.start)}</span>
                  <span className="f">{s.speaker && <b>المتحدث {s.speaker}: </b>}{s.text}</span></div>
              )) : <span className="mu">{tr?.summary}</span>}
            </section>
            <Checks m={m} />
          </>
        )}
      </div>
      <div className="side">
        {m && <Verdict m={m} />}
        {m && (
          <section className="card" aria-label="مقارنة تسجيلين">
            <h2>قارن بتسجيل آخر</h2>
            <span className="mu" style={{ fontSize: 12 }}>بصمة صوتية: هل هو التسجيل نفسه (ولو قُصّ أو أعيد ضغطه)؟</span>
            <select className="inp" value={other} onChange={(e) => setOther(e.target.value)} aria-label="التسجيل الآخر">
              <option value="">اختر تسجيلًا…</option>
              {recent.filter((r) => r.id !== m.id).map((r) => <option key={r.id} value={r.id}>{r.filename || `#${r.id}`} · {fmt(r.seen_at)}</option>)}
            </select>
            <button className="btn" disabled={!other} onClick={compare}>قارن</button>
            {err && <div className="msg err">{err}</div>}
            {cmp && <div role="status"><span className={`pill ${gradePill(cmp.grade)}`}>{gradeText(cmp.grade)}</span> {cmp.verdict} — تطابق {Math.round(cmp.similarity * 100)}٪{cmp.similarity >= 0.62 ? `، بإزاحة ${cmp.offset_s} ث` : ""}</div>}
          </section>
        )}
        <section className="card">
          <h2>آخر التسجيلات</h2>
          {!recent.length && <span className="mu">لا تسجيلات بعد.</span>}
          {recent.map((r) => (
            <div key={r.id} className="row">
              <span className="f">{r.filename || `#${r.id}`}<br /><span className="mu">{fmt(r.seen_at)}</span></span>
              <button className="btn sm" onClick={() => nav(`/audio-lab/${r.id}`)}>افتح</button>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
