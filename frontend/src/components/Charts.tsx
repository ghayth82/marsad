// رسوم بيانية خفيفة بـ SVG وألوان النمط الحالي: أشرطة أفقية، خط زمني بعلامة، وخريطة حرارية.
// سلسلة واحدة في كل رسم (لون التمييز)، والقيم مكتوبة نصًا فلا يعتمد شيء على اللون وحده.
import { useState, type ReactNode } from "react";

export type Drill = { kind: "claims" | "items"; ids: number[] };
export type Metric = { n: number; drill: Drill };

type Tip = { x: number; y: number; text: string } | null;

function Tooltip({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div role="status" style={{ position: "fixed", insetInlineStart: undefined, left: tip.x + 12, top: tip.y + 12, zIndex: 50,
      background: "var(--tx)", color: "var(--sf)", padding: "6px 9px", borderRadius: 8, fontSize: 12, pointerEvents: "none",
      maxWidth: 280, whiteSpace: "pre-wrap" }}>{tip.text}</div>
  );
}

/** أشرطة أفقية: الاسم، الشريط، القيمة. كل صف يُنقر فيفتح ما حُسب منه. */
export function Bars({ rows, onPick, unit = "" }: { rows: { key: string; n: number; drill?: Drill; note?: string }[];
  onPick?: (title: string, d: Drill) => void; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  if (!rows.length) return <span className="mu">لا بيانات في هذه الفترة.</span>;
  return (
    <div role="list" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {rows.map((r) => {
        const click = r.drill && r.n > 0 && onPick ? () => onPick(r.key, r.drill!) : undefined;
        return (
          <button key={r.key} role="listitem" type="button" onClick={click} disabled={!click}
            style={{ display: "grid", gridTemplateColumns: "minmax(90px,30%) 1fr auto", gap: 10, alignItems: "center", border: "none",
              background: "none", padding: "3px 0", cursor: click ? "pointer" : "default", color: "var(--tx)", fontFamily: "inherit",
              fontSize: 13, textAlign: "start" }} title={r.note}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.key}</span>
            <span style={{ height: 14, background: "var(--sf2)", borderRadius: 4, overflow: "hidden" }}>
              <span style={{ display: "block", height: "100%", width: `${(100 * r.n) / max}%`, minWidth: r.n ? 4 : 0,
                background: "var(--ac)", borderRadius: 4 }} />
            </span>
            <b style={{ minWidth: 28, textAlign: "end" }}>{r.n}{unit}</b>
          </button>
        );
      })}
    </div>
  );
}

/** خط زمني لعدد المواد في كل فترة، مع خط عمودي عند وقت الحكم. */
export function Timeline({ points, marker, height = 160, compact = false, onPick, bucket = "hour" }: {
  points: { t: string; items: number; sources: number; ids: number[] }[]; marker?: string | null; height?: number;
  compact?: boolean; onPick?: (title: string, d: Drill) => void; bucket?: string }) {
  const [tip, setTip] = useState<Tip>(null);
  const [hover, setHover] = useState<number | null>(null);
  if (!points.length) return <span className="mu">لا ظهورات مسجّلة.</span>;
  const W = 600, H = height, pad = compact ? 4 : 24;
  const max = Math.max(1, ...points.map((p) => p.items));
  const t0 = Date.parse(points[0].t), t1 = Date.parse(points[points.length - 1].t) || t0 + 1;
  const span = Math.max(1, t1 - t0);
  // الاتجاه من اليمين: الأقدم يمينًا كما يُقرأ الخط الزمني بالعربية
  const x = (t: number) => W - pad - ((t - t0) / span) * (W - 2 * pad);
  const y = (v: number) => H - pad - (v / max) * (H - 2 * pad);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(Date.parse(p.t)).toFixed(1)},${y(p.items).toFixed(1)}`).join(" ");
  const fmt = (t: string) => new Date(t).toLocaleString("ar", bucket === "hour" ? { day: "numeric", month: "short", hour: "2-digit" } : { day: "numeric", month: "short" });
  const mx = marker ? x(Date.parse(marker)) : null;
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={compact ? 48 : H} preserveAspectRatio="none" role="img"
        aria-label={`منحنى الانتشار: ${points.reduce((a, p) => a + p.items, 0)} مادة`}
        onMouseLeave={() => { setTip(null); setHover(null); }}>
        {!compact && <line x1={pad} x2={W - pad} y1={H - pad} y2={H - pad} stroke="var(--bd)" strokeWidth={1} />}
        <path d={d} fill="none" stroke="var(--ac)" strokeWidth={2} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        {mx != null && <line x1={mx} x2={mx} y1={pad / 2} y2={H - pad} stroke="var(--tx)" strokeDasharray="4 3" strokeWidth={1.5} vectorEffect="non-scaling-stroke" />}
        {!compact && hover != null && <circle cx={x(Date.parse(points[hover].t))} cy={y(points[hover].items)} r={4} fill="var(--ac)" stroke="var(--sf)" strokeWidth={2} />}
        {!compact && points.map((p, i) => {
          const cx = x(Date.parse(p.t)), w = Math.max(6, (W - 2 * pad) / points.length);
          return <rect key={i} x={cx - w / 2} y={0} width={w} height={H} fill="transparent" style={{ cursor: p.items && onPick ? "pointer" : "default" }}
            onMouseMove={(e) => { setHover(i); setTip({ x: e.clientX, y: e.clientY, text: `${fmt(p.t)}\n${p.items} مادة من ${p.sources} مصدر` }); }}
            onClick={() => p.items && onPick?.(`مواد ${fmt(p.t)}`, { kind: "items", ids: p.ids })} />;
        })}
      </svg>
      {!compact && (
        <div className="mu" style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
          <span>{fmt(points[0].t)}</span>
          {marker && <span>- - - وقت اعتماد الحكم</span>}
          <span>{fmt(points[points.length - 1].t)}</span>
        </div>
      )}
      <Tooltip tip={tip} />
    </div>
  );
}

const DAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"];

/** خريطة حرارية يوم × ساعة: لون واحد يشتد مع العدد، والعدد في التلميح. */
export function Heatmap({ cells, onPick }: { cells: { day: number; hour: number; n: number; drill: Drill }[];
  onPick?: (title: string, d: Drill) => void }) {
  const [tip, setTip] = useState<Tip>(null);
  const max = Math.max(1, ...cells.map((c) => c.n));
  const at = (d: number, h: number) => cells.find((c) => c.day === d && c.hour === h);
  return (
    <div className="tw" onMouseLeave={() => setTip(null)}>
      <div style={{ display: "grid", gridTemplateColumns: "64px repeat(24, minmax(14px,1fr))", gap: 2, minWidth: 480, fontSize: 10.5 }}>
        <span />
        {Array.from({ length: 24 }, (_, h) => <span key={h} className="mu" style={{ textAlign: "center", fontSize: 10 }}>{h % 3 === 0 ? h : ""}</span>)}
        {DAYS.map((name, d) => [
          <span key={`l${d}`} className="mu" style={{ fontSize: 11 }}>{name}</span>,
          ...Array.from({ length: 24 }, (_, h) => {
            const c = at(d, h);
            const n = c?.n ?? 0;
            return <button key={`${d}-${h}`} type="button" aria-label={`${name} الساعة ${h}: ${n} مادة`}
              onMouseMove={(e) => setTip({ x: e.clientX, y: e.clientY, text: `${name} ${String(h).padStart(2, "0")}:00\n${n} مادة` })}
              onClick={() => c && n && onPick?.(`${name} الساعة ${h}`, c.drill)}
              style={{ height: 18, border: "none", borderRadius: 3, padding: 0, cursor: n ? "pointer" : "default",
                background: n ? `color-mix(in srgb, var(--ac) ${Math.round(15 + 85 * (n / max))}%, var(--sf2))` : "var(--sf2)" }} />;
          }),
        ])}
      </div>
      <div className="mu" style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 6, fontSize: 11 }}>
        أقل <span style={{ width: 60, height: 8, borderRadius: 4, background: "linear-gradient(to left, var(--ac), var(--sf2))" }} /> أكثر (بتوقيت عمّان)
      </div>
      <Tooltip tip={tip} />
    </div>
  );
}

/** بطاقة رقم واحد قابلة للنقر. */
export function Kpi({ label, value, sub, onClick }: { label: string; value: ReactNode; sub?: ReactNode; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} disabled={!onClick} className="card"
      style={{ textAlign: "start", cursor: onClick ? "pointer" : "default", fontFamily: "inherit", color: "var(--tx)", gap: 2 }}>
      <span className="big">{value}</span>
      <span>{label}</span>
      {sub && <span className="mu">{sub}</span>}
    </button>
  );
}
