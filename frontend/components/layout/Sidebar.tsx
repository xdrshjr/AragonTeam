"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, type ReactNode } from "react";
import { BrandLockup } from "@/components/brand/BrandLogo";
import { useAuth } from "@/lib/auth";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
  // 命中前缀即高亮（用于 board 子路由）。
  match?: string;
}

function Icon({ path }: { path: string }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={path} />
    </svg>
  );
}

const NAV: NavItem[] = [
  {
    href: "/dashboard",
    label: "仪表盘",
    icon: <Icon path="M3 13h8V3H3zM13 21h8V3h-8zM3 21h8v-6H3z" />,
  },
  {
    href: "/my-work",
    label: "我的工作",
    icon: <Icon path="M20 6 9 17l-5-5" />,
  },
  {
    // 【version-plan-console §5.4】层级树的入口，排在「需求」之前——它是需求 / BUG
    // 的上层容器，阅读顺序应当自上而下。图标取「层叠 / 分支」意象。
    href: "/versions",
    label: "版本",
    match: "/versions",
    icon: <Icon path="M12 2 3 7l9 5 9-5zM3 12l9 5 9-5M3 17l9 5 9-5" />,
  },
  {
    href: "/requirements",
    label: "需求",
    match: "/requirements",
    icon: <Icon path="M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />,
  },
  {
    href: "/bugs",
    label: "BUG",
    match: "/bugs",
    icon: <Icon path="M8 2l1.88 1.88M14.12 3.88L16 2M9 7.13v-1a3.003 3.003 0 1 1 6 0v1M12 20v-9M6.53 9C4 9 4 12 4 12M18 12s0-3-2.53-3M6 13H2M22 13h-4M6 17H4M20 17h-2" />,
  },
  {
    href: "/agents",
    label: "Agent",
    icon: <Icon path="M12 8V4M8 8h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2zM9 14h.01M15 14h.01M9 18h6" />,
  },
  {
    href: "/team",
    label: "团队",
    icon: <Icon path="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />,
  },
  {
    href: "/projects",
    label: "项目",
    match: "/projects",
    icon: <Icon path="M3 7a2 2 0 0 1 2-2h4l2 2h6a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  },
  {
    href: "/documents",
    label: "文档",
    match: "/documents",
    icon: <Icon path="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8zM14 2v6h6M16 13H8M16 17H8M10 9H8" />,
  },
  {
    href: "/settings",
    label: "设置",
    icon: <Icon path="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />,
  },
];

// 【login-hardening-and-audit-console §5.5】仅根管理员可见的导航项。插在「设置」**之前**
// （设置在导航末位是既有约定，不挤走它）。R-13：user 未就绪（undefined）时不渲染它——
// 宁可晚出现一项，不可先出现再消失。
const ROOT_ONLY_NAV: NavItem[] = [
  {
    href: "/audit",
    label: "审计",
    match: "/audit",
    icon: <Icon path="M9 12l2 2 4-4M12 3l7 4v5c0 5-3.5 8-7 9-3.5-1-7-4-7-9V7z" />,
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { user } = useAuth();

  // 审计项插在「设置」之前；user 未就绪或非根管理员时就是原样的 NAV。
  const items = useMemo(() => {
    if (!user?.is_root) return NAV;
    const idx = NAV.findIndex((n) => n.href === "/settings");
    if (idx < 0) return [...NAV, ...ROOT_ONLY_NAV];
    return [...NAV.slice(0, idx), ...ROOT_ONLY_NAV, ...NAV.slice(idx)];
  }, [user]);

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-border bg-surface">
      <div className="flex h-16 items-center border-b border-border px-5">
        <BrandLockup className="h-7 w-[166px]" priority />
      </div>

      <nav className="flex-1 space-y-1 p-3">
        {items.map((item) => {
          const active = item.match
            ? pathname.startsWith(item.match)
            : pathname === item.href;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={[
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-clay-soft/60 font-medium text-clay-dark"
                  : "text-ink-muted hover:bg-black/[0.04] hover:text-ink",
              ].join(" ")}
            >
              <span className={active ? "text-clay-dark" : "text-ink-muted"}>
                {item.icon}
              </span>
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-border p-4 text-xs text-ink-muted">
        <div className="font-medium text-ink">AI 协作 · MVP</div>
        <div className="mt-0.5">Agent 是一等公民</div>
      </div>
    </aside>
  );
}
