"use client";

// 一次性口令的**唯一一次**展示（account-security-and-governance §6.2）。
//
// 这是本产品里少数几个「误关就丢数据」的对话框之一，故：
// ① 关掉遮罩这条路径（`dismissOnBackdrop={false}`）——遮罩误点会销毁唯一的凭据。
//    Esc 与标题栏的 ✕ 仍然照常关闭：那两个是用户的明确动作，把它们一起做成空操作
//    等于留一个点了没反应的死控件，键盘与读屏用户尤其受伤；
// ② 口令用等宽大字号呈现，便于口述与手抄（生成时已去掉 0/O/1/l/I 等易混字符）；
// ③ 复制失败必须说出来（共用 ui/CopyButton）。

import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import CopyButton from "@/components/ui/CopyButton";

interface Props {
  /** null → 关闭。 */
  password: string | null;
  /** 这个口令是给谁的（显示名），用于「请立刻发给 XXX」。 */
  memberName: string;
  onClose: () => void;
}

export default function TemporaryPasswordDialog({ password, memberName, onClose }: Props) {
  return (
    <Modal
      open={!!password}
      onClose={onClose}
      dismissOnBackdrop={false}
      title="一次性密码"
      width={480}
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-ink-muted">
          已为 <span className="font-medium text-ink">{memberName}</span> 生成一次性密码。
          他首次登录后会被要求立即修改，在那之前无法使用系统的其他功能。
        </p>

        <div className="flex items-center gap-2">
          <div className="flex h-12 flex-1 select-all items-center overflow-x-auto rounded-lg border border-border bg-black/[0.02] px-3 font-mono text-lg tracking-wider text-ink">
            {password}
          </div>
          <CopyButton value={password ?? ""} label="一次性密码" size="md" />
        </div>

        <p className="rounded-lg border border-[#E8C9BC] bg-[#F3D2C7]/30 px-3 py-2 text-sm text-[#B23B1E]">
          <strong>这是唯一一次看到它</strong>，关闭后任何接口都读不回来；请立刻发给{" "}
          {memberName}。
        </p>

        <div className="mt-1 flex justify-end">
          <Button onClick={onClose}>我已保存并发送</Button>
        </div>
      </div>
    </Modal>
  );
}
