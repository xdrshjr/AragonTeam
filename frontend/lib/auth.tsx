"use client";

// AuthProvider + useAuth（§3.3 lib/auth.tsx）。登录态、token 存取、会话复原。

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { api, setToken, getToken, ApiError } from "@/lib/api";
import type { SignupPayload, User } from "@/lib/types";

interface AuthState {
  user: User | null;
  loading: boolean; // 初始会话复原中
  login: (username: string, password: string) => Promise<void>;
  /** 自助注册并**直接登录**（self-service-registration §2.2 B-2）：
   *  后端 201 的响应体与 /auth/login 的 200 完全同形，故落地逻辑与 login 逐行同构。 */
  signup: (payload: SignupPayload) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  // 就地刷新登录态（如自助改资料后），免一次 /auth/me 往返（account-settings §7）。
  applyUser: (u: User) => void;
}

const AuthContext = createContext<AuthState | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  // 刷新时用 token 复原会话（GET /auth/me）。
  const restore = useCallback(async () => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      const { user } = await api.get<{ user: User }>("/auth/me");
      setUser(user);
    } catch (e) {
      // token 失效/过期 → 清除。
      setToken(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    restore();
  }, [restore]);

  // 【§2.8】会话过期全局登出：api.ts 在 401（非 /auth/ 路径）时广播 aragon:unauthorized；
  // 此处订阅后清态，setUser(null) 触发 (app)/layout 既有守卫跳登录（幂等，无循环）。
  useEffect(() => {
    function onUnauth() {
      setToken(null);
      setUser(null);
    }
    window.addEventListener("aragon:unauthorized", onUnauth);
    return () => window.removeEventListener("aragon:unauthorized", onUnauth);
  }, []);

  // 【account-security-and-governance §2.2 B-3】强制改密闸门的 403：**这不是登出**。
  // token 仍然有效，只是这个人欠一次改密——重新拉一次 /auth/me 把
  // must_change_password 读回来，(app)/layout 的守卫据此把他送去 /force-password。
  // 监听器与 restore() 在同一个组件里，作用域天然可达（对外仍只暴露 refresh()）。
  useEffect(() => {
    function onPasswordChangeRequired() {
      restore();
    }
    window.addEventListener("aragon:password-change-required", onPasswordChangeRequired);
    return () =>
      window.removeEventListener("aragon:password-change-required", onPasswordChangeRequired);
  }, [restore]);

  const login = useCallback(async (username: string, password: string) => {
    const { token, user } = await api.post<{ token: string; user: User }>(
      "/auth/login",
      { username, password }
    );
    setToken(token);
    setUser(user);
  }, []);

  // 与上面的 login 逐行同构：拿到 {token, user} → 写 token → 写登录态。
  // 失败一律向上抛 ApiError，由表单按 status / detail.field 渲染**字段级**错误
  // （403 邀请码错误必须落在邀请码字段下方，而不是一个无处着落的 toast）。
  const signup = useCallback(async (payload: SignupPayload) => {
    const { token, user } = await api.post<{ token: string; user: User }>(
      "/auth/signup",
      payload
    );
    setToken(token);
    setUser(user);
  }, []);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  const refresh = useCallback(async () => {
    await restore();
  }, [restore]);

  const applyUser = useCallback((u: User) => setUser(u), []);

  return (
    <AuthContext.Provider
      value={{ user, loading, login, signup, logout, refresh, applyUser }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
