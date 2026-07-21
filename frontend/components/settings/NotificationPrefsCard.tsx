"use client";

import { useNotificationPreferences } from "@/hooks/useNotificationPreferences";
import { NOTIFICATION_LABELS, NOTIFICATION_ICONS } from "@/lib/constants";
import { useToast } from "@/lib/toast";
import Toggle from "@/components/ui/Toggle";
import ErrorState from "@/components/ui/ErrorState";
import { NOTIFICATION_TYPE_LIST, type NotificationType } from "@/lib/types";

// 各类通知的展示顺序 = `NOTIFICATION_TYPE_LIST`（lib/types.ts，与联合类型同处维护）。
// 【self-service-registration §2.3 C-1 / R-17】此处**曾是手写镜像**：漏加一项不会编译
// 失败，只会让新类型变成一个用户永远关不掉的通知。改为从单一列表派生后，那种漏改
// 已经不可能发生——列表和联合类型漂移会在 lib/types.ts 当场编译报错。

// 通知偏好卡（account-settings §7）：逐类开关，拨动即乐观更新，失败自动回滚 + toast。
export default function NotificationPrefsCard() {
  const { preferences, loading, error, refresh, setPreference } = useNotificationPreferences();
  const toast = useToast();

  async function onToggle(type: NotificationType, next: boolean) {
    try {
      await setPreference(type, next);
    } catch {
      // rollbackOnError 已把乐观态回滚，这里仅提示。
      toast.error("偏好更新失败，已回滚");
    }
  }

  return (
    <section className="rounded-xl border border-border bg-surface p-6 shadow-card">
      <h2 className="font-serif text-lg text-ink">通知偏好</h2>
      <p className="mt-1 text-sm text-ink-muted">关闭某类型后，该类型通知将不再产生。</p>

      {/* 【§2.8④】数据未知时**绝不**把开关画成任何一个具体状态：此前 GET 失败会渲染成
          「六个开关全开且全部锁死」，用户会确信通知都开着。改为整组以错误态替代。 */}
      {error && !preferences ? (
        <ErrorState message="无法加载通知偏好" onRetry={() => refresh()} />
      ) : (
      <ul className="mt-5 divide-y divide-border">
        {NOTIFICATION_TYPE_LIST.map((type) => {
          const enabled = preferences?.[type] ?? true;
          return (
            <li key={type} className="flex items-center justify-between py-3">
              <span className="flex items-center gap-2.5 text-sm text-ink">
                <span aria-hidden="true" className="w-5 text-center">
                  {NOTIFICATION_ICONS[type]}
                </span>
                {NOTIFICATION_LABELS[type]}
              </span>
              <Toggle
                checked={enabled}
                disabled={loading || !preferences}
                label={`${NOTIFICATION_LABELS[type]}通知`}
                onChange={(next) => onToggle(type, next)}
              />
            </li>
          );
        })}
      </ul>
      )}

      <p className="mt-4 text-xs text-ink-muted">
        「指派」开关同时作用于 Agent 认领你工单的提醒（二者共用同一通知类型）。
      </p>
    </section>
  );
}
