const TOKEN_KEY = "ato_token";

let token: string | null = localStorage.getItem(TOKEN_KEY);

export function getToken(): string | null {
  return token;
}

export function setToken(t: string | null): void {
  token = t;
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildUrl(path: string, query?: Query): string {
  const qs = new URLSearchParams();
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    }
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

export function errorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: any) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((x: unknown) => x !== "body").join(".") : "";
        const msg = String(d?.msg ?? d).replace(/^Value error, /, "");
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join("; ");
  }
  return fallback;
}

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: unknown; query?: Query } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), {
      method: opts.method ?? "GET",
      headers,
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch (e) {
    throw new ApiError(0, `Сервер недоступен: ${(e as Error).message}`);
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    if (res.status === 401 && token && !path.startsWith("/api/auth/login")) {
      setToken(null);
      window.dispatchEvent(new Event("ato:logout"));
    }
    throw new ApiError(res.status, errorMessage(data?.detail, `HTTP ${res.status}`));
  }
  return data as T;
}
