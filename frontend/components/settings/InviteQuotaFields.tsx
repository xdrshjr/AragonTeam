"use client";

// 邀请码的期限 + 额度 + 用量（login-hardening-and-audit-console §5.1）。
//
// 挂进 RegistrationCard 的「邀请码」与「默认角色」之间。三条交互都对应一个可预见的困惑：
//  - 时间以 UTC 存储，输入框旁常驻显示换算结果，否则一定有人填错八小时；
//  - 过去的时刻前端先拦一次（disabled + 内联错误），不让用户提交完才吃 400；
//  - 用量条颜色分三档，且**状态文案始终在旁边**，颜色不是唯一信息载体（WCAG 1.4.1）。

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/toast";
import type { RegistrationSettings } from "@/lib/types";
import type { RegistrationSettingsPatch } from "@/hooks/useRegistrationSettings";
import Button from "@/components/ui/Button";
import Input from "@/components/ui/Input";
import ProgressBar from "@/components/ui/ProgressBar";

interface Props {
  settings: RegistrationSettings;
  update: (patch: RegistrationSettingsPatch) => Promise<void>;
}

const INVITE_STATUS_TEXT: Record<RegistrationSettings["invite_status"], string> = {
  active: "生效中",
  expired: "已过期",
  exhausted: "已用尽",
  disabled: "已关闭",
};

/** UTC ISO（带 Z）→ `<input type="datetime-local">` 需要的**本地**时间串 `YYYY-MM-DDTHH:mm`。 */
function utcIsoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours()
  )}:${pad(d.getMinutes())}`;
}

/** 本地 datetime-local 串 → UTC 显示（`YYYY-MM-DD HH:mm`），供输入框旁的换算提示。 */
function localInputToUtcHint(local: string): string {
  if (!local) return "";
  const d = new Date(local);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().slice(0, 16).replace("T", " ");
}

export default function InviteQuotaFields({ settings, update }: Props) {
  const toast = useToast();
  const [expiry, setExpiry] = useState("");
  const [maxUses, setMaxUses] = useState("0");
  const [savingExpiry, setSavingExpiry] = useState(false);
  const [savingMax, setSavingMax] = useState(false);

  useEffect(() => {
    setExpiry(utcIsoToLocalInput(settings.invite_expires_at));
  }, [settings.invite_expires_at]);
  useEffect(() => {
    setMaxUses(String(settings.invite_max_uses));
  }, [settings.invite_max_uses]);

  const errText = (err: unknown) => (err instanceof ApiError ? err.message : "保存失败");

  // 过去的时刻前端先拦（后端那道 400 才是权威，这道只为体验）。
  const expiryInPast = expiry !== "" && new Date(expiry).getTime() <= Date.now();
  const expiryDirty =
    (expiry === "" ? null : expiry) !== utcIsoToLocalInput(settings.invite_expires_at) ||
    (expiry === "" && settings.invite_expires_at !== null);

  async function onSaveExpiry() {
    if (expiryInPast) return;
    setSavingExpiry(true);
    try {
      await update({ expires_at: expiry === "" ? null : new Date(expiry).toISOString() });
      toast.success(expiry === "" ? "已清除有效期" : "有效期已更新");
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSavingExpiry(false);
    }
  }

  async function onSaveMax() {
    const n = Number(maxUses);
    if (!Number.isInteger(n) || n < 0 || n > 10000) {
      return toast.error("名额上限须是 0~10000 的整数");
    }
    setSavingMax(true);
    try {
      await update({ max_uses: n });
      toast.success(n === 0 ? "已设为不限名额" : `名额上限已设为 ${n}`);
    } catch (err) {
      toast.error(errText(err));
    } finally {
      setSavingMax(false);
    }
  }

  const { invite_uses: uses, invite_max_uses: max, invite_status: status } = settings;
  const limited = max > 0;
  const percent = limited ? Math.round((uses / max) * 100) : null;
  const nearLimit = percent !== null && percent >= 80 && percent < 100;
  const atLimit =
    (percent !== null && percent >= 100) || status === "exhausted" || status === "expired";
  const barClass = atLimit
    ? "[&>div]:bg-clay-dark"
    : nearLimit
      ? "[&>div]:bg-clay"
      : "[&>div]:bg-ink-muted";
  const statusTone =
    status === "active"
      ? "text-ink-muted"
      : status === "disabled"
        ? "text-ink-muted"
        : "text-clay-dark";

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-border/70 bg-black/[0.015] p-4">
      {/* 有效期 */}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-end gap-2">
          <Input
            label="有效期至"
            name="invite_expires_at"
            type="datetime-local"
            className="min-w-[13rem] flex-1"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
          />
          <Button size="sm" disabled={savingExpiry || expiryInPast || !expiryDirty}
                  onClick={onSaveExpiry}>
            {savingExpiry ? "保存中…" : "保存"}
          </Button>
          <Button variant="ghost" size="sm" disabled={savingExpiry || expiry === ""}
                  onClick={() => setExpiry("")}>
            清除
          </Button>
        </div>
        <p className="text-xs text-ink-muted">
          {expiryInPast ? (
            <span className="text-clay-dark">有效期必须是将来的时刻</span>
          ) : expiry !== "" ? (
            <>= UTC {localInputToUtcHint(expiry)}（本产品按 UTC 存储时间）</>
          ) : (
            <>留空 = 永不过期</>
          )}
        </p>
      </div>

      {/* 名额上限 */}
      <div className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-end gap-2">
          <Input
            label="名额上限"
            name="invite_max_uses"
            type="number"
            min={0}
            max={10000}
            className="w-28"
            value={maxUses}
            onChange={(e) => setMaxUses(e.target.value)}
          />
          <Button size="sm" disabled={savingMax || maxUses === String(max)}
                  onClick={onSaveMax}>
            {savingMax ? "保存中…" : "保存"}
          </Button>
          <span className="pb-2.5 text-xs text-ink-muted">0 = 不限</span>
        </div>
      </div>

      {/* 用量 */}
      <div className="flex flex-col gap-1.5">
        {limited ? (
          <ProgressBar value={percent} label="邀请码名额用量" className={barClass} />
        ) : (
          <div className="h-1.5 w-full rounded-full bg-black/[0.06]" aria-hidden="true" />
        )}
        <div className="flex items-center justify-between text-xs">
          <span className="text-ink-muted">
            {limited ? `已用 ${uses} / ${max}` : `已用 ${uses} 个（不限名额）`}
          </span>
          <span className={statusTone}>状态：{INVITE_STATUS_TEXT[status]}</span>
        </div>
      </div>
    </div>
  );
}
