"use client";

// 段级错误边界（Phase-2 §2.7）——(app) 路由组内任一页渲染出错时兜底，避免白屏。
import { useEffect } from "react";
import Button from "@/components/ui/Button";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // 仅记录到控制台，不泄露给用户（与后端「不泄露堆栈」一致）。
    console.error(error);
  }, [error]);

  return (
    <div className="flex h-full flex-1 flex-col items-center justify-center gap-4 p-10 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-clay-soft/50 text-clay-dark">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 9v4M12 17h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        </svg>
      </div>
      <div>
        <h2 className="font-serif text-xl text-ink">这个页面出了点问题</h2>
        <p className="mt-1 max-w-md text-sm text-ink-muted">
          我们已记录该错误。你可以重试当前操作；若持续失败，请确认后端服务是否在运行。
        </p>
      </div>
      <div className="flex items-center gap-2">
        <Button onClick={reset}>重试</Button>
        <Button variant="ghost" onClick={() => (window.location.href = "/dashboard")}>
          回到仪表盘
        </Button>
      </div>
    </div>
  );
}
