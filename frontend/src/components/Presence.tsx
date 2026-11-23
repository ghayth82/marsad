// من يفتح الصفحة نفسها الآن: نبضة كل 15 ثانية، و«يكتب» لمن يحرّر.
import { useEffect, useState } from "react";
import { api } from "../api";

export function Presence({ path, editing = false }: { path: string; editing?: boolean }) {
  const [others, setOthers] = useState<{ user_id: number; name: string; editing: boolean }[]>([]);
  useEffect(() => {
    let alive = true;
    const beat = () => api<{ others: typeof others }>("/api/presence", { method: "POST", body: { path, editing } })
      .then((r) => alive && setOthers(r.others)).catch(() => {});
    beat();
    const t = setInterval(beat, 15000);
    return () => { alive = false; clearInterval(t); };
  }, [path, editing]);
  if (!others.length) return null;
  return (
    <div className="msg" role="status" aria-label="الحاضرون" style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
      <span>يعمل هنا الآن:</span>
      {others.map((o) => <span key={o.user_id} className={`pill ${o.editing ? "p-warn" : "p-ac"}`}>{o.name}{o.editing ? " · يكتب" : ""}</span>)}
    </div>
  );
}
