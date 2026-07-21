"use client";

// 注册配置卡（self-service-registration §2.3 C-4）——**仅根管理员可见**。
//
// 非根管理员连卡片都不渲染（挂载方 app/(app)/settings/page.tsx 做的判断），
// 避免「看得见但一按就 403」的挫败感。后端 `@require_root()` 才是真正的门禁，
// 这里的隐藏纯粹是体验层面的。

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import { useRegistrationSettings } from "@/hooks/useRegistrationSettings";
import { ROLE_LABELS } from "@/lib/constants";
import type { Role } from "@/lib/types";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
// 【account-security-and-governance §3.5】内联的 CopyButton 已提取为共用组件（本轮第三个调用点）。
import CopyButton from "@/components/ui/CopyButton";
import Select from "@/components/ui/Select";
import Toggle from "@/components/ui/Toggle";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import ErrorState from "@/components/ui/ErrorState";
import { SkeletonRows } from "@/components/ui/Skeleton";
import InviteQuotaFields from "@/components/settings/InviteQuotaFields";

function errText(err: unknown): string {
  return err instanceof ApiError ? err.message : "保存失败";
}

export default function RegistrationCard() {
  const toast = useToast();
  const { settings, loading, error, refresh, update, rotate } = useRegistrationSettings(true);
  const [code, setCode] = useState("");
  const [revealed, setRevealed] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [saving, setSaving] = useState(false);

  // 服务端值到达 / 变化后同步进输入框；用户正在编辑时不打断（仅在值本身变化时覆盖）。
  useEffect(() => {
    if (settings) setCode(settings.invite_code);
  }, [settings?.invite_code]);

  async function onToggleEnabled(next: boolean) {
    try {
      await update({ enabled: next });
      toast.success(next ? "已开放自助注册" : "已关闭自助注册");
    } catch (err) {
      toast.error(errText(err));
    }
  }

  async function onSaveCode() {
    const trimmed = code.trim();
    if (trimmed === settings?.invite_code) return toast.info("邀请码没有变化");
    setSaving(true);
    try {
      await update({ invite_code: trimmed });
      toast.success("邀请码已更新，旧码立即失效");
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSaving(false);
    }
  }

  async function onChangeRole(next: Role) {
    try {
      await update({ default_role: next });
      toast.success(`新用户默认角色已设为「${ROLE_LABELS[next]}」`);
    } catch (err) {
      toast.error(errText(err));
    }
  }

  if (error && !settings) {
    return (
      <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
        <h2 className="font-serif text-lg text-ink">注册配置</h2>
        <ErrorState message="无法加载注册配置" onRetry={() => refresh()} />
      </section>
    );
  }
  if (!settings) {
    return (
      <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
        <h2 className="font-serif text-lg text-ink">注册配置</h2>
        <SkeletonRows rows={3} />
      </section>
    );
  }

  const roleOptions = settings.allowed_default_roles.map((r) => ({
    value: r,
    label: ROLE_LABELS[r],
  }));
  const registerUrl =
    typeof window === "undefined" ? "/register" : `${window.location.origin}/register`;

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="font-serif text-lg text-ink">注册配置</h2>
          <p className="mt-1 text-sm text-ink-muted">
            开放后，任何拿到邀请码的人都可以自己建号并直接登录。
          </p>
        </div>
        <Toggle
          checked={settings.enabled}
          disabled={loading}
          label="开放自助注册"
          onChange={onToggleEnabled}
        />
      </div>

      {/* 关闭后下方整体降为禁用态并灰化——而不是隐藏：管理员需要看见「关掉的是什么」。 */}
      <div
        className={[
          "mt-6 flex flex-col gap-5",
          settings.enabled ? "" : "pointer-events-none opacity-50",
        ].join(" ")}
        aria-disabled={!settings.enabled}
      >
        <div className="flex flex-col gap-2">
          <div className="flex items-end gap-2">
            <Input
              label="邀请码"
              name="invite_code"
              className="flex-1"
              type={revealed ? "text" : "password"}
              autoComplete="off"
              spellCheck={false}
              maxLength={64}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <Button
              variant="ghost"
              size="sm"
              aria-pressed={revealed}
              aria-label={revealed ? "隐藏邀请码" : "显示邀请码"}
              onClick={() => setRevealed((v) => !v)}
            >
              {revealed ? "隐藏" : "显示"}
            </Button>
            <CopyButton value={settings.invite_code} label="邀请码" />
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" disabled={saving} onClick={onSaveCode}>
              {saving ? "保存中…" : "保存邀请码"}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setRotating(true)}>
              重新生成
            </Button>
            <span className="text-xs text-ink-muted">4~64 个字符，不含空格</span>
          </div>
        </div>

        {/* 【login-hardening-and-audit-console §5.1】邀请码的期限 / 额度 / 用量。 */}
        <InviteQuotaFields settings={settings} update={update} />

        <Select
          label="新用户默认角色"
          name="default_role"
          value={settings.default_role}
          options={roleOptions}
          onChange={(e) => onChangeRole(e.target.value as Role)}
        />

        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-ink">注册链接</span>
          <div className="flex items-center gap-2">
            <div className="flex h-10 flex-1 items-center overflow-x-auto rounded-lg border border-border bg-black/[0.02] px-3 text-sm text-ink-muted">
              {registerUrl}
            </div>
            <CopyButton value={registerUrl} label="注册链接" />
          </div>
        </div>
      </div>

      <p className="mt-6 border-t border-border pt-4 text-xs text-ink-muted">
        「管理员」不在可选默认角色里——一个知道邀请码的人不该能直接成为管理员。
        <br />
        根管理员的账号与密码在后端配置文件（<code>ROOT_ADMIN_*</code>）中定义，此处不可修改；
        它是所有管理员都进不来时唯一的破窗入口。
        {settings.updated_by && settings.updated_at && (
          <>
            <br />
            最近一次修改：{settings.updated_by.name} · {settings.updated_at.slice(0, 10)}
          </>
        )}
      </p>

      <ConfirmDialog
        open={rotating}
        title="重新生成邀请码"
        danger
        confirmLabel="确认重新生成"
        description={
          <>
            将立刻生成一个全新的随机邀请码。
            <strong className="text-ink">旧邀请码立即失效</strong>
            ，任何还没用它注册的人都需要重新向你索取；
            <strong className="text-ink">已注册的账号不受影响</strong>。
            <br />
            <span className="text-ink-muted">
              已用名额将重新从 0 计起，有效期与名额上限保持不变。
            </span>
          </>
        }
        onConfirm={async () => {
          await rotate();
          setRotating(false);
          toast.success("已生成新邀请码");
        }}
        onClose={() => setRotating(false)}
      />
    </section>
  );
}
