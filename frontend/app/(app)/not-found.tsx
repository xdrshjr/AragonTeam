// 段级 404（Phase-2 §2.7）——统一 Anthropic 风格，避免默认白页。
import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex h-full flex-1 flex-col items-center justify-center gap-4 p-10 text-center">
      <div className="font-serif text-5xl text-clay">404</div>
      <div>
        <h2 className="font-serif text-xl text-ink">找不到这个页面</h2>
        <p className="mt-1 text-sm text-ink-muted">
          你访问的内容不存在，或已被移动。
        </p>
      </div>
      <Link
        href="/dashboard"
        className="rounded-lg bg-clay px-4 py-2 text-sm font-medium text-white shadow-card hover:bg-clay-dark"
      >
        回到仪表盘
      </Link>
    </div>
  );
}
