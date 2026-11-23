import { useSession } from "../session";

export const DASHBOARD_CARDS: Record<string, string> = {
  rising_stories: "القصص الصاعدة",
  new_rumors: "شائعات جديدة",
  alerts: "التنبيهات",
  sources_status: "حالة المصادر",
  daily_brief: "موجز اليوم",
  my_cases: "قضاياي",
  pending_approvals: "بانتظار اعتمادي",
  engine_costs: "كلفة المحركات",
  training: "التدريب",
};

// اللوحة تعرض البطاقات التي اختارها المستخدم وبترتيبه.
// البيانات تأتي مع بنود الرصد والشائعات؛ حتى ذلك الحين تظهر حالة فارغة صادقة، لا أرقام وهمية.
export function Dashboard() {
  const { me } = useSession();
  if (!me) return null;
  const cards = me.preferences.dashboard;
  return (
    <>
      {cards.length === 0 && <div className="card"><span className="mu">لوحتك فارغة. أضف بطاقات من «تفضيلاتي».</span></div>}
      <div className="g4">
        {cards.map((k) => (
          <section className="card" key={k}>
            <h2>{DASHBOARD_CARDS[k] ?? k}</h2>
            <span className="mu">لا بيانات بعد. تظهر هنا حين تُضاف المصادر ويبدأ الرصد.</span>
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
