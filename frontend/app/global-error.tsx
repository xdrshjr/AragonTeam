"use client";

// 根级错误兜底（Phase-2 §2.7）——连 root layout 都崩时的最后防线。
// 必须自带 <html>/<body>（它替换了根布局）。
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="zh-CN">
      <body
        style={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#F7F4EE",
          color: "#1A1A17",
          fontFamily: "system-ui, Inter, sans-serif",
        }}
      >
        <div style={{ textAlign: "center", padding: 40 }}>
          <h2 style={{ fontFamily: "Georgia, serif", fontSize: 22, marginBottom: 8 }}>
            应用发生了意外错误
          </h2>
          <p style={{ color: "#6E6A62", fontSize: 14, marginBottom: 16 }}>
            请刷新页面重试。
          </p>
          <button
            onClick={reset}
            style={{
              backgroundColor: "#C15F3C",
              color: "#fff",
              border: "none",
              borderRadius: 8,
              padding: "8px 16px",
              fontSize: 14,
              cursor: "pointer",
            }}
          >
            重试
          </button>
        </div>
      </body>
    </html>
  );
}
