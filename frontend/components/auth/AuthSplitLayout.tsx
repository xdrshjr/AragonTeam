"use client";

// 登录 / 注册共用的双栏骨架（self-service-registration §6.1）。
//
// 从 `app/login/page.tsx` 原样抽出：左品牌区 `bg-clay-soft/40`（`lg` 以下整块隐藏、
// 品牌 lockup 上移到表单顶部），右表单区 `bg-bg` 居中。抽出来的理由不是复用几行 JSX，
// 而是**两页的第一印象必须一致**——注册页若长得像另一个产品，会让人怀疑自己点错了链接。

import type { ReactNode } from "react";
import { BrandLockup } from "@/components/brand/BrandLogo";

interface Props {
  /** 右栏标题（如「欢迎回来」/「创建你的账号」）。 */
  title: string;
  /** 标题下的一句话说明。 */
  subtitle: string;
  /** 右栏主体：表单或空态。 */
  children: ReactNode;
  /** 右栏底部的次要动作区（如「已有账号？去登录」）。 */
  footer?: ReactNode;
}

export default function AuthSplitLayout({ title, subtitle, children, footer }: Props) {
  return (
    <div className="flex min-h-screen">
      {/* 左侧品牌区 */}
      <div className="hidden flex-1 flex-col justify-between bg-clay-soft/40 p-12 lg:flex">
        <BrandLockup className="h-10 w-[236px]" priority />
        <div className="max-w-md">
          <h1 className="font-serif text-4xl leading-tight text-ink">
            AI 时代的
            <br />
            团队协作平台
          </h1>
          <p className="mt-4 text-ink-muted">
            需求与 BUG 不只指派给人，也能指派给 Agent。人与 AI
            混合协作的每一步流转，都被完整记录。
          </p>
        </div>
        <div className="text-sm text-ink-muted">© AragonTeam · Anthropic 风格设计</div>
      </div>

      {/* 右侧表单区 */}
      <div className="flex flex-1 items-center justify-center bg-bg p-6">
        <div className="w-full max-w-sm py-10">
          <div className="mb-8 lg:hidden">
            <BrandLockup className="h-9 w-[212px]" priority />
          </div>
          <h2 className="font-serif text-2xl text-ink">{title}</h2>
          <p className="mt-1 text-sm text-ink-muted">{subtitle}</p>
          {children}
          {footer && <div className="mt-6 text-center text-sm">{footer}</div>}
        </div>
      </div>
    </div>
  );
}
