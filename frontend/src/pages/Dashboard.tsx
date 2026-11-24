import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useSession } from "../session";

type Task = { id: number; text: string; priority: string; priority_ar: string; overdue: boolean; due_at: string | null };

export const DASHBOARD_CARDS: Record<string, string> = {
  rising_stories: "القصص الصاعدة",
  new_rumors: "شائعات جديدة",
  alerts: "التنبيهات",
  sources_status: "حالة المصادر",
  daily_brief: "موجز اليوم",
  my_tasks: "مهامي",
  my_cases: "قضاياي",
  pending_approvals: "بانتظار اعتمادي",
  engine_costs: "كلفة المحركات",
  training: "التدريب",
};

type Dash = {
  rising_stories?: { id: number; title: string; outlets: number; new_items: number; link: string }[];
  new_rumors?: { items: { id: number; text: string; link: string }[]; count: number; returns: { id: number; text: string; link: string }[] };
  alerts?: { id: number; kind: string; text: string; at: string; read: boolean }[];
  sources_status?: { ok: number; error: number; new: number; paused: number; total: number; broken: { id: number; title: string; error: string }[] };
  daily_brief?: { id: number; created_at: string; text: string } | null;
  my_cases?: { id: number; title: string; link: string }[];
  my_tasks?: { tasks: Task[]; review: Task[] };
  pending_approvals?: { kind: string; text: string; link: string }[];
  engine_costs?: { month_usd: number };
  training?: { total: number; done: number; next: { id: number; title: string; link: string } | null };
};

const Empty = ({ t }: { t: string }) => <span className="mu">{t}</span>;
const linkify = (t: string) => { const m = t.match(/\/(claims|reports|stories)\/\d+/); return m ? m[0] : null; };

// اللوحة تعرض البطاقات التي اختارها المستخدم وبترتيبه، ببيانات حقيقية؛ والبطاقة الفارغة تقول ذلك صراحة.
export function Dashboard() {
  const { me } = useSession();
  const [d, setD] = useState<Dash | null>(null);
  useEffect(() => {
    const load = () => api<Dash>("/api/dashboard").then(setD).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);
  if (!me) return null;
  const cards = me.preferences.dashboard;
  const body = (k: string) => {
    if (!d) return <Empty t="يجري التحميل…" />;
    switch (k) {
      case "rising_stories":
        return d.rising_stories?.length ? d.rising_stories.map((s) => <div key={s.id} className="row"><Link className="f" to={s.link}>{s.title}</Link><span className="pill p-ac">{s.outlets} مصادر</span></div>)
          : <Empty t="لا قصص صاعدة في آخر 6 ساعات." />;
      case "new_rumors":
        return d.new_rumors ? (<>
          <b>{d.new_rumors.count} ادّعاء في 24 ساعة</b>
          {d.new_rumors.returns.map((r) => <div key={r.id} className="row"><span className="pill p-bad">عادت</span><Link className="f" to={r.link}>{r.text}</Link></div>)}
          {d.new_rumors.items.map((r) => <div key={r.id} className="row"><Link className="f" to={r.link}>{r.text}</Link></div>)}
        </>) : <Empty t="لا صلاحية رصد." />;
      case "alerts":
        return d.alerts?.length ? d.alerts.map((a) => { const l = linkify(a.text); return <div key={a.id} className="row"><span className="f" style={{ fontSize: 13 }}>{l ? <Link to={l}>{a.text.replace(l, "")}</Link> : a.text}</span></div>; })
          : <Empty t="لا تنبيهات." />;
      case "sources_status":
        return d.sources_status ? (<>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}><span className="pill p-ok">{d.sources_status.ok} تعمل</span>{d.sources_status.error > 0 && <span className="pill p-bad">{d.sources_status.error} متوقفة</span>}<span className="pill p-n">{d.sources_status.total} مصدرًا</span></div>
          {d.sources_status.broken.map((s) => <div key={s.id} className="row"><span className="f mu" style={{ fontSize: 12 }}>{s.title}: {s.error}</span></div>)}
          {!d.sources_status.total && <Link to="/sources">أضف مصادر</Link>}
        </>) : <Empty t="لا صلاحية رصد." />;
      case "daily_brief":
        return d.daily_brief ? <><p style={{ whiteSpace: "pre-wrap", fontSize: 13 }}>{d.daily_brief.text}</p><Link to={`/reports/${d.daily_brief.id}`}>الموجز كاملًا</Link></>
          : <Empty t="يُنشأ الموجز الصباحي تلقائيًا في موعده." />;
      case "my_tasks": {
        const t = d.my_tasks;
        if (!t || (!t.tasks.length && !t.review.length)) return <Empty t="لا مهام مسندة إليك." />;
        return <>{t.tasks.map((x) => <div key={x.id} className="row"><Link className="f" to={`/claims/${x.id}`}>{x.text}</Link>
          <span className={`pill ${x.overdue ? "p-bad" : x.priority === "urgent" ? "p-warn" : "p-n"}`}>{x.overdue ? "تجاوز المهلة" : x.priority_ar}</span></div>)}
          {t.review.length > 0 && <span className="mu">بانتظار مراجعتك</span>}
          {t.review.map((x) => <div key={`r${x.id}`} className="row"><Link className="f" to={`/claims/${x.id}`}>{x.text}</Link><span className="pill p-ac">مراجعة</span></div>)}</>;
      }
      case "my_cases":
        return d.my_cases?.length ? d.my_cases.map((c) => <div key={c.id} className="row"><Link className="f" to={c.link}>{c.title}</Link></div>) : <Empty t="لا قضايا." />;
      case "pending_approvals":
        return d.pending_approvals?.length ? d.pending_approvals.map((p, i) => <div key={i} className="row"><span className="pill p-warn">{p.kind}</span><Link className="f" to={p.link}>{p.text}</Link></div>) : <Empty t="لا شيء بانتظارك." />;
      case "engine_costs":
        return d.engine_costs ? <b>{d.engine_costs.month_usd.toFixed(2)} $ هذا الشهر</b> : <Empty t="لا صلاحية محركات." />;
      case "training":
        return d.training ? <><b>{d.training.done} من {d.training.total} تمرينًا</b>{d.training.next && <div><Link to={d.training.next.link}>التالي: {d.training.next.title}</Link></div>}</> : <Empty t="لا تدريب." />;
    }
    return null;
  };
  return (
    <>
      {cards.length === 0 && <div className="card"><span className="mu">لوحتك فارغة. أضف بطاقات من «تفضيلاتي».</span></div>}
      <div className="g4">
        {cards.map((k) => (
          <section className="card" key={k} data-card={k}>
            <h2>{DASHBOARD_CARDS[k] ?? k}</h2>
            {body(k)}
          </section>
        ))}
      </div>
    </>
  );
}

export function Placeholder({ title }: { title: string }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      <span className="mu">هذا القسم قيد البناء ضمن خطة البناء الكاملة، ويظهر هنا حين يكتمل.</span>
    </section>
  );
}
