// عميل الخادم: كل الطلبات بنفس الأصل، مع ترويسة الحماية من الطلبات المزوّرة.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method ?? "GET",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-Marsad": "1" },
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
  } catch {
    throw new ApiError(0, "تعذّر الاتصال بالخادم");
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? "قيمة غير صحيحة في الحقول"
      : res.status >= 500 ? `حدث خطأ داخلي في الخادم (${res.status}). سُجّل في سجل الخادم.`
      : `تعذّر تنفيذ الطلب (${res.status})`;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export type Appearance = {
  font: "noto" | "naskh" | "plex" | "readex";
  leading: "normal" | "comfy" | "wide";
  read_scale: number;
  read_width: "narrow" | "medium" | "full";
  accent: "teal" | "blue" | "indigo" | "purple" | "graphite";
  contrast: boolean;
  density: "comfortable" | "compact";
  hints: boolean;
};

export const DEFAULT_APPEARANCE: Appearance = { font: "noto", leading: "comfy", read_scale: 1, read_width: "medium", accent: "teal", contrast: false, density: "comfortable", hints: true };

export type Prefs = {
  pattern: "a" | "b" | "c";
  theme: "light" | "dark" | "system";
  language: "ar" | "en";
  font_scale: number;
  appearance: Appearance;
  tour_done: boolean;
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

/** رفع نموذج (ملفات) بالترويسة نفسها؛ المتصفح يضع حدود multipart بنفسه. */
export async function apiForm<T = unknown>(path: string, form: FormData): Promise<T> {
  const res = await fetch(path, { method: "POST", credentials: "same-origin", headers: { "X-Marsad": "1" }, body: form });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const d = data?.detail;
    throw new ApiError(res.status, typeof d === "string" ? d : "تعذّر رفع الملف");
  }
  return data as T;
}
