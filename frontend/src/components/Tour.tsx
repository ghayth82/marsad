// الجولة التعريفية: خمس محطات قصيرة عند أول دخول. تُتخطّى في أي لحظة، وتُعاد من «الدليل» أو «تفضيلاتي».
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Prefs } from "../api";
import { useSession } from "../session";

const STOPS: { title: string; text: string; to?: string; go?: string }[] = [
  { title: "أهلًا بك في مرصد التحقق", text: "البرنامج يتابع المواقع والقنوات التي تختارها، ويحفظ ما تنشره، ويساعدك في التحقق من الأخبار والصور والتسجيلات. هذه جولة من خمس محطات، دقيقة واحدة." },
  { title: "1. أضف مصادرك", text: "من «المصادر» الصق رابط موقع أو قناة، والبرنامج يتولى الباقي. أو أضف القائمة المقترحة (50 مصدرًا) بضغطة.", to: "/sources", go: "افتح المصادر" },
  { title: "2. تابع الأخبار", text: "في «الرصد» تظهر الأخبار أولًا بأول. اضغط أي خبر لتقرأه، وترى إن عدّله الموقع أو حذفه بعد نشره.", to: "/live", go: "افتح الرصد" },
  { title: "3. تحقّق", text: "سجّل الجملة المشكوك فيها في «الشائعات»، واجمع أدلتها. وافحص أي صورة أو فيديو أو تسجيل من قسم «أتحقق».", to: "/rumors", go: "افتح الادّعاءات" },
  { title: "4. التلميحات معك دائمًا", text: "قف بالفأرة على أي زر أو عنوان فيظهر شرحه. علامة ⓘ تعني أن للعنوان شرحًا. زر «» في الأعلى يخفي التلميحات ويظهرها متى شئت، وزر «؟» يشرح الشاشة التي أنت فيها." },
];

export function Tour({ onClose }: { onClose: () => void }) {
  const { me, savePrefs } = useSession();
  const nav = useNavigate();
  const [i, setI] = useState(0);
  if (!me) return null;
  const s = STOPS[i];
  const last = i === STOPS.length - 1;
  const finish = () => { savePrefs({ tour_done: true } as Partial<Prefs>); onClose(); };
  return (
    <div className="tour-back" role="dialog" aria-modal="true" aria-labelledby="tour-h">
      <div className="tour-card">
        <span className="mu">{i + 1} من {STOPS.length}</span>
        <h2 id="tour-h" style={{ margin: 0 }}>{s.title}</h2>
        <p style={{ margin: 0, lineHeight: 1.9 }}>{s.text}</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {i > 0 && <button className="btn" onClick={() => setI(i - 1)}>السابق</button>}
          {!last && <button className="btn pri" onClick={() => setI(i + 1)}>التالي</button>}
          {last && <button className="btn pri" onClick={finish}>ابدأ العمل</button>}
          {s.to && <button className="btn" onClick={() => { finish(); nav(s.to!); }}>{s.go}</button>}
          <span style={{ flex: 1 }} />
          {!last && <button className="linkish" onClick={finish}>تخطَّ الجولة</button>}
        </div>
      </div>
    </div>
  );
}
