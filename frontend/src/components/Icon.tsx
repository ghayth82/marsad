// أيقونات مرسومة موحّدة (خطوط بلون النص) بدل الرموز التعبيرية التي يختلف شكلها بين الأجهزة.
const P: Record<string, string> = {
  home: "M3 11l9-7 9 7M5 10v10h5v-6h4v6h5V10",
  sources: "M12 20v-8M8.5 8.5a5 5 0 017 0M5.5 5.5a9 9 0 0113 0M12 12h.01M8 20h8",
  live: "M4 5h13v14H5a1 1 0 01-1-1V5zM17 9h3v9a1 1 0 01-1 1h-2M7 9h7M7 12h7M7 15h4",
  stories: "M4 6h7v5H4zM13 6h7v5h-7zM4 13h7v5H4zM16.5 13v5M14 15.5h5",
  rumors: "M4 5h16v11H10l-4 4v-4H4zM12 8v3.5M12 14h.01",
  claims: "M6 3h9l4 4v14H6zM15 3v4h4M9 13l2 2 4-4",
  media: "M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 5M8.5 9h.01",
  audio: "M12 3a3 3 0 00-3 3v5a3 3 0 006 0V6a3 3 0 00-3-3zM6 11a6 6 0 0012 0M12 17v4M9 21h6",
  tools: "M14.5 6.5a4 4 0 00-5.3 5.3L3 18l3 3 6.2-6.2a4 4 0 005.3-5.3L15 12l-3-3z",
  cases: "M3 7h6l2 2h10v10H3zM3 7V5h6l2 2",
  write: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
  entities: "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20a6 6 0 0112 0M16 5.5a3 3 0 010 5.5M17.5 14.5A6 6 0 0121 20",
  reports: "M7 4h10v17H7zM10 2h4v4h-4zM10 10h4M10 14h4M10 18h2",
  stats: "M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-8",
  ratings: "M12 4v16M8 20h8M5 7h14M5 7l-3 6a3 3 0 006 0zM19 7l-3 6a3 3 0 006 0z",
  engines: "M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3M6 6h12v12H6zM10 10h4v4h-4z",
  training: "M2 9l10-5 10 5-10 5zM6 11.5V16c2 2 10 2 12 0v-4.5M22 9v5",
  admin: "M12 9a3 3 0 100 6 3 3 0 000-6zM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2",
  help: "M12 21a9 9 0 100-18 9 9 0 000 18zM9.5 9.5a2.5 2.5 0 114 2c-1 .7-1.5 1.2-1.5 2.5M12 17h.01",
  archive: "M3 5h18v4H3zM5 9v10h14V9M10 13h4",
  hint: "M9 18h6M10 21h4M12 3a6 6 0 00-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0012 3z",
};

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return (
    <svg className="ic" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={P[name] ?? P.help} />
    </svg>
  );
}
