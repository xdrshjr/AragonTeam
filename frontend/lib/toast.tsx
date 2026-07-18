"use client";

// 轻量全局 toast（支撑 spec U4/U6 与 useBoard「回滚 + toast」诉求）。
// 说明：spec 文件清单未单列 toast 原语，此文件为实现「toast 错误提示」的最小支撑，
// 已在 spec.md「实施过程发现的方案缺陷」记录。

import {
  createContext,
  useCallback,
  useContext,
  useState,
  ReactNode,
} from "react";

type ToastKind = "success" | "error" | "info";
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

interface ToastApi {
  push: (message: string, kind?: ToastKind) => void;
  success: (message: string) => void;
  error: (message: string) => void;
  info: (message: string) => void;
}

const ToastContext = createContext<ToastApi | undefined>(undefined);

let _seq = 1;

const KIND_STYLE: Record<ToastKind, { bg: string; fg: string; icon: string }> = {
  success: { bg: "#D9EBDD", fg: "#3E7A4F", icon: "✓" },
  error: { bg: "#F3D2C7", fg: "#B23B1E", icon: "!" },
  info: { bg: "#DCE7F2", fg: "#3B6EA5", icon: "i" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    (message: string, kind: ToastKind = "info") => {
      const id = _seq++;
      setToasts((prev) => [...prev, { id, kind, message }]);
      setTimeout(() => remove(id), 3800);
    },
    [remove]
  );

  const api: ToastApi = {
    push,
    success: (m) => push(m, "success"),
    error: (m) => push(m, "error"),
    info: (m) => push(m, "info"),
  };

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="pointer-events-none fixed bottom-6 right-6 z-[60] flex flex-col gap-2">
        {toasts.map((t) => {
          const s = KIND_STYLE[t.kind];
          return (
            <div
              key={t.id}
              onClick={() => remove(t.id)}
              className="pointer-events-auto flex max-w-sm items-start gap-2 rounded-lg border border-border bg-surface px-4 py-3 text-sm shadow-lift"
            >
              <span
                className="mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold"
                style={{ backgroundColor: s.bg, color: s.fg }}
              >
                {s.icon}
              </span>
              <span className="text-ink">{t.message}</span>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}
