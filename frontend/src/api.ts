// عميل الخادم: كل الطلبات بنفس الأصل، مع ترويسة الحماية من الطلبات المزوّرة.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch(path, {
    method: opts.method ?? "GET",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Marsad": "1" },
    body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
  });
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? "قيمة غير صحيحة في الحقول" : "تعذّر الاتصال بالخادم";
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export type Prefs = {
  pattern: "a" | "b" | "c";
  theme: "light" | "dark" | "system";
  language: "ar" | "en";
  font_scale: number;
  dashboard: string[];
  view_as_role: string | null;
  follows: Record<string, string[]>;
  saved_filters: unknown[];
  engines: Record<string, string>;
  alerts: { channels: string[]; urgent_only: boolean; quiet_hours: [number, number] | null };
};

export type RoleAccess = { key: string; name_ar: string; expires_at: string | null; active: boolean; permissions: string[] };
export type Override = { permission: string; effect: "grant" | "deny"; expires_at: string | null; active: boolean };
export type Access = { roles: RoleAccess[]; overrides: Override[]; effective: string[] };

export type Me = {
  id: number;
  email: string;
  full_name: string;
  totp_enabled: boolean;
  access: Access;
  preferences: Prefs;
  permission_labels: Record<string, string>;
};
