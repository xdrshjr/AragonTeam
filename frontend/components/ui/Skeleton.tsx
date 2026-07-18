// 骨架屏原语（Phase-2 §2.7）——替换纯文字「加载中…」，减少布局跳动。
// 纯 CSS 脉冲动画（animate-pulse 由 Tailwind 提供），零新增依赖。

interface SkeletonProps {
  className?: string;
}

// 单个骨架块。
export function Skeleton({ className = "" }: SkeletonProps) {
  return (
    <div
      className={["animate-pulse rounded-md bg-black/[0.06]", className].join(" ")}
      aria-hidden="true"
    />
  );
}

// 列表行骨架（表格加载态）。
export function SkeletonRows({ rows = 6 }: { rows?: number }) {
  return (
    <div className="divide-y divide-border" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3.5">
          <Skeleton className="h-4 w-14" />
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="h-5 w-16" />
          <Skeleton className="h-6 w-6 rounded-full" />
        </div>
      ))}
    </div>
  );
}

// 看板列骨架（横向若干列，每列若干卡）。
export function SkeletonBoard({ columns = 5, cards = 3 }: { columns?: number; cards?: number }) {
  return (
    <div className="flex h-full gap-4 overflow-hidden" aria-hidden="true">
      {Array.from({ length: columns }).map((_, c) => (
        <div key={c} className="flex w-72 shrink-0 flex-col gap-2">
          <Skeleton className="mb-1 h-4 w-24" />
          {Array.from({ length: cards }).map((_, k) => (
            <Skeleton key={k} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      ))}
    </div>
  );
}

// 抽屉内容骨架。
export function SkeletonDrawer() {
  return (
    <div className="space-y-4 p-5" aria-hidden="true">
      <Skeleton className="h-6 w-2/3" />
      <Skeleton className="h-4 w-full" />
      <Skeleton className="h-4 w-5/6" />
      <Skeleton className="h-20 w-full rounded-lg" />
      <Skeleton className="h-4 w-1/2" />
      <Skeleton className="h-14 w-full rounded-lg" />
      <Skeleton className="h-14 w-full rounded-lg" />
    </div>
  );
}

export default Skeleton;
