// 展示层格式化工具（login-hardening-and-audit-console §3.3 / 评审 P1-5）。
//
// `relTime` 此前有两份逐字相同的副本（MemberActivityModal 与 NotificationBell），
// 审计页是第三个消费者——再复制一份就成了「一个公共件 + 三份副本」。这里收口为唯一真相。
// 行为逐字不变：刚刚 / N 分钟前 / N 小时前 / N 天前 / 超过 30 天走 toLocaleDateString。

/**
 * 把一个带 Z 的 ISO 时刻渲染成中文相对时间。
 *
 * @param iso 后端 `to_dict` 输出的时间串（恒带尾部 Z，正确解析为本地时间）。
 * @param dateOptions 超过 30 天时 `toLocaleDateString("zh-CN", ...)` 的选项。
 *   两个既有调用点的日期格式**本就不同**（时间线含年份、通知铃铛不含），故作为参数
 *   透传，保证收口后两侧输出逐字节不变。缺省含年月日。
 */
export function relTime(iso: string, dateOptions?: Intl.DateTimeFormatOptions): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const diff = Date.now() - d.getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "刚刚";
  if (m < 60) return `${m} 分钟前`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} 小时前`;
  const day = Math.floor(h / 24);
  if (day < 30) return `${day} 天前`;
  return d.toLocaleDateString(
    "zh-CN",
    dateOptions ?? { year: "numeric", month: "2-digit", day: "2-digit" }
  );
}
