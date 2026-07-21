// fetch 封装（§3.3 lib/api.ts）。自动带 token、统一错误、ApiError。
// 契约：所有非 2xx 响应体恒为 { error: string, detail?: any }（后端 §2.6 保证）。

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://localhost:5000/api";

const TOKEN_KEY = "aragon_token";

/** `/projects` 的唯一 SWR key。ProjectScopeProvider 与 projects 页必须共用它，
 *  否则两份缓存互不失效：新建项目后切换器下拉里看不到它（scale-and-project-scope 评审 R4）。
 *  值里的 `limit=200`（= 后端 MAX_LIMIT）对应 §2.9-G1 给 /projects 加的分页，
 *  避免默认 50 条上限静默截断项目列表。
 *
 *  【lifecycle-and-governance §2.6】本 key **不含归档项目**（后端 `GET /api/projects`
 *  默认只返回未归档），这正是切换器与建单表单想要的语义。 */
export const PROJECTS_KEY = "/projects?limit=200";

/** `/projects` **含归档**的 SWR key，仅项目管理页使用——它必须能看到归档项目才能取消归档。
 *  与 `PROJECTS_KEY` 是**两个 key 两种形状**（scale-and-project-scope 评审 R4 的不变量：
 *  同一个 key 下的响应形状必须唯一），故刻意不复用；与 `PROJECTS_KEY` 并列声明在这里，
 *  是为了让「谁看得到归档项目」这件事在同一屏内一目了然。 */
export const PROJECTS_ALL_KEY = "/projects?limit=200&include_archived=1";

/** `/users` 的唯一 SWR key（同 PROJECTS_KEY 的理由；G1 后须显式传 limit 防 50 条截断）。 */
export const USERS_KEY = "/users?limit=200";

/** `/agents` 的唯一 SWR key（同上）。 */
export const AGENTS_KEY = "/agents?limit=200";

/** 文档库首页的 SWR key 前缀（ticket-document-management）。带 `?` 的完整 key 由
 *  `useDocumentLibrary` 依筛选条件拼出；这里只固化前缀，供 `invalidateDocumentViews`
 *  与各页共用同一个字面量。 */
export const DOCUMENTS_KEY = "/documents";

/** 公开注册元信息的唯一 SWR key（登录页与注册页共用；**不含邀请码**）。 */
export const REGISTRATION_META_KEY = "/auth/registration-meta";

/** 根管理员专属的注册设置 key（含明文邀请码，非根管理员一律 403）。 */
export const REGISTRATION_SETTINGS_KEY = "/settings/registration";

/** 站点治理审计的**路径前缀**（login-hardening-and-audit-console §3.4 / 评审 P1-7）。
 *  **有意不叫 `*_KEY`**：本文件顶部的不变量是「一个 `*_KEY` ⇒ 一种响应形状，分页 / 带
 *  筛选的视图不得复用它们」（`USERS_KEY = "/users?limit=200"` 正是被点名的反例）。审计页
 *  是分页 + 4 筛选的，页面 key 由 `useGovernanceAudit` 内联拼；这个常量只作前缀，
 *  供失效前缀与 hook 拼串。 */
export const GOVERNANCE_AUDIT_PREFIX = "/settings/audit";

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

// 会话过期/失效的全局信号（§2.8）：401（非 /auth/ 路径）→ 清 token 并广播 aragon:unauthorized，
// 由 AuthProvider 落地为登出 + 外壳跳登录。排除 /auth/ 路径——登录接口的 401（凭据错误）不是
// 「会话过期」，不应触发登出重定向。api.ts 不 import auth，用 CustomEvent 事件总线避免环依赖。
export function signalUnauthorizedIfNeeded(path: string, status: number) {
  if (status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
    setToken(null);
    window.dispatchEvent(new CustomEvent("aragon:unauthorized"));
  }
}

/** 后端强制改密闸门的 403（account-security-and-governance §4.6）。
 *
 *  形状与上面的 `signalUnauthorizedIfNeeded` 逐条对齐，**但绝不 `setToken(null)`**——
 *  那是登出，而这里的语义是「你还登录着，只是欠一次改密」。由 AuthProvider 订阅后
 *  刷新登录态，`(app)/layout` 的既有守卫据此把人送去 `/force-password`。
 */
export function signalPasswordChangeRequired(status: number, error?: string) {
  if (status === 403 && error === "password change required" && typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("aragon:password-change-required"));
  }
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
    signalUnauthorizedIfNeeded(path, res.status);
    signalPasswordChangeRequired(res.status, data?.error);
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
    signalUnauthorizedIfNeeded(path, res.status);
    signalPasswordChangeRequired(res.status, body?.error);
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

// —— ticket-document-management：上传（带进度）与二进制下载 ——
//
// 【为什么需要一条 XHR 分支】`fetch` **没有上传进度事件**。这是 lib/api.ts 需要 XHR 的
// **唯一**理由，其余请求继续走 fetch，不要顺手迁移。

export interface UploadProgress {
  loaded: number;
  total: number;
  /** 0~100；total 未知时为 null（不要伪造一个假百分比）。 */
  percent: number | null;
}

export interface UploadOptions {
  onProgress?: (p: UploadProgress) => void;
  /** 拿到 XHR 后可保存引用以便取消（用户的文件、用户的带宽，由用户决定）。 */
  onStart?: (xhr: XMLHttpRequest) => void;
}

/**
 * multipart 上传，带真实进度。
 *
 * **绝不手设 `Content-Type`**：浏览器要自己写 `multipart/form-data; boundary=…`，
 * 手设会让 boundary 丢失、后端解析不出任何字段。
 */
export function uploadWithProgress<T>(
  path: string,
  form: FormData,
  options: UploadOptions = {}
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}${path}`);
    const token = getToken();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);

    xhr.upload.onprogress = (e) => {
      options.onProgress?.({
        loaded: e.loaded,
        total: e.total,
        percent: e.lengthComputable && e.total > 0
          ? Math.round((e.loaded / e.total) * 100)
          : null,
      });
    };

    xhr.onload = () => {
      let data: any = null;
      if (xhr.responseText) {
        try {
          data = JSON.parse(xhr.responseText);
        } catch {
          data = null;
        }
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(data as T);
        return;
      }
      // 【必须复用】否则上传路径的 401 不会触发全局登出，用户会看到一个永远失败的
      // 进度条而不知道自己已经掉线。
      signalUnauthorizedIfNeeded(path, xhr.status);
      reject(new ApiError(xhr.status, (data && data.error) || `上传失败（${xhr.status}）`,
                          data?.detail, data?.allowed));
    };
    xhr.onerror = () => reject(new ApiError(0, "无法连接服务器，请确认后端已启动"));
    xhr.onabort = () => reject(new ApiError(0, "已取消上传"));

    options.onStart?.(xhr);
    xhr.send(form);
  });
}

export interface DownloadedBlob {
  blob: Blob;
  /** 后端 `Content-Disposition` 里的 `filename*`，解码后的原始文件名。 */
  filename: string | null;
}

/**
 * 带 JWT 取二进制内容。
 *
 * **调用方注意（§2.6 / 评审 R6）**：拿到 blob 后若要构造 `objectURL` 用于预览，
 * Blob 的 `type` **只能**取自后端 `mime_type` 字段（数据库值，非用户可控）并经
 * `INLINE_SAFE_MIMES` 白名单过滤——`blob:` 文档的 MIME 完全由前端入参决定、与任何
 * 响应头无关，且它运行在**本源**（JWT 就存在这个源的 localStorage 里）。
 */
export async function downloadBlob(path: string): Promise<DownloadedBlob> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { method: "GET", headers });
  } catch {
    throw new ApiError(0, "无法连接服务器，请确认后端已启动");
  }
  if (!res.ok) {
    signalUnauthorizedIfNeeded(path, res.status);
    let data: any = null;
    try {
      data = JSON.parse(await res.text());
    } catch {
      data = null;
    }
    throw new ApiError(res.status, (data && data.error) || `下载失败（${res.status}）`,
                       data?.detail);
  }
  return { blob: await res.blob(), filename: parseFilename(res.headers.get("Content-Disposition")) };
}

function parseFilename(disposition: string | null): string | null {
  if (!disposition) return null;
  const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    return null;
  }
}

/** 触发浏览器「另存为」。objectURL 用完立刻 revoke，不留悬挂引用。 */
export function saveBlobAs(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
