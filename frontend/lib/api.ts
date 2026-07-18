// fetch 封装（§3.3 lib/api.ts）。自动带 token、统一错误、ApiError。
// 契约：所有非 2xx 响应体恒为 { error: string, detail?: any }（后端 §2.6 保证）。

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:5000/api";

const TOKEN_KEY = "aragon_token";

export class ApiError extends Error {
  status: number;
  detail?: unknown;
  allowed?: string[];
  constructor(status: number, message: string, detail?: unknown, allowed?: string[]) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.allowed = allowed;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  // GET 查询参数（自动过滤 undefined/null/空串）。
  params?: Record<string, string | number | undefined | null>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, params } = options;

  let url = `${API_BASE}${path}`;
  if (params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.append(k, String(v));
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    // 网络错误（后端未启动等）——规整成 ApiError，前端可统一 toast。
    throw new ApiError(0, "无法连接服务器，请确认后端已启动");
  }

  if (res.status === 204) return undefined as T;

  // 错误体恒为 JSON（§2.6）；仍做一层防御，避免极端情况解析崩溃。
  let data: any = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!res.ok) {
    const message =
      (data && (data.error as string)) || `请求失败（${res.status}）`;
    throw new ApiError(res.status, message, data?.detail, data?.allowed);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string, params?: RequestOptions["params"]) =>
    request<T>(path, { method: "GET", params }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

// SWR fetcher（默认 GET）。
export const swrFetcher = <T>(path: string) => api.get<T>(path);

// —— 【R-01】返回 headers 的读取路径 ——
// 既有 request() 只回 body、丢弃 res.headers，无法读分页头 X-Total-Count；
// 此函数额外返回 headers，配合后端 CORS expose_headers（§2.5-7）跨域可读。
export async function getWithHeaders<T>(
  path: string,
  params?: RequestOptions["params"]
): Promise<{ data: T; headers: Headers }> {
  let url = `${API_BASE}${path}`;
  if (params) {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== "") qs.append(k, String(v));
    }
    const s = qs.toString();
    if (s) url += `?${s}`;
  }

  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(url, { method: "GET", headers });
  } catch {
    throw new ApiError(0, "无法连接服务器，请确认后端已启动");
  }

  let body: any = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }
  if (!res.ok) {
    const message = (body && (body.error as string)) || `请求失败（${res.status}）`;
    throw new ApiError(res.status, message, body?.detail, body?.allowed);
  }
  return { data: body as T, headers: res.headers };
}

// 列表 SWR fetcher：返回裸数组 + 从 X-Total-Count 读出的总数（渐进采用分页）。
export async function listFetcher<T>(path: string): Promise<{ items: T[]; total: number }> {
  const { data, headers } = await getWithHeaders<T[]>(path);
  const items = Array.isArray(data) ? data : [];
  const raw = headers.get("X-Total-Count");
  const total = raw !== null && !Number.isNaN(Number(raw)) ? Number(raw) : items.length;
  return { items, total };
}
