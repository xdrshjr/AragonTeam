"use client";

import useSWR, { useSWRConfig } from "swr";
import { useCallback } from "react";
import { api, swrFetcher, ApiError } from "@/lib/api";
import { toHierarchyQuery, type HierarchyFilterValue } from "@/lib/hierarchy";
import { invalidateHierarchyViews } from "@/lib/swr-keys";
import { useToast } from "@/lib/toast";
import type { ProjectScope } from "@/lib/project-scope";
import type { Board, Card } from "@/lib/types";

type Entity = "requirements" | "bugs";

/** 每列最多拉多少张卡（= 后端 board_page.DEFAULT_COLUMN_LIMIT）。
 *  超出部分由列头「显示 x / 共 y」+「查看全部」出口承接（§2.8）。 */
export const BOARD_COLUMN_LIMIT = 100;

// 看板数据拉取 + 乐观移动 + 回滚（§2.2 B / U3 / U4）。
// 第二参为项目作用域（scale-and-project-scope §2.4⑦）：null=全部、"none"=未归属、number=该项目。
// **必须**用 `== null` 判据而非真值判据——旧写法无法表达 "none"，且会把 id 0 当作「不过滤」。
// 第三参为「版本 → 计划」级联筛选（version-plan-console §5.5）：类型从 lib/hierarchy
// **import type**，绝不反向依赖 "use client" 组件的导出（层级倒置）。
export function useBoard(entity: Entity, scope?: ProjectScope,
                         hierarchy?: HierarchyFilterValue) {
  const toast = useToast();
  const { mutate: globalMutate } = useSWRConfig();
  // 【lifecycle-and-governance §2.8】显式带上 column_limit：看板每列有上限（后端默认 100），
  // 写进 key 而非依赖后端默认值，是为了让「一个 key 一种形状」这条不变量在改上限时仍成立。
  const scopeParam = scope == null ? "" : `project_id=${scope}&`;
  const hierarchyParam = hierarchy ? toHierarchyQuery(hierarchy) : "";
  const key = `/board/${entity}?${scopeParam}${hierarchyParam ? `${hierarchyParam}&` : ""}`
    + `column_limit=${BOARD_COLUMN_LIMIT}`;
  const { data, error, isLoading, mutate } = useSWR<Board<Card>>(key, swrFetcher);

  // 把某卡移动到 toStatus 列的 toIndex 位置（乐观更新，失败回滚 + toast）。
  // toIndex 缺省 = 追加列尾；支持同列精确重排（Phase-2 §2.6）。
  const move = useCallback(
    async (cardId: number, toStatus: string, toIndex?: number) => {
      if (!data) return;

      // 定位卡片与源列。
      let card: Card | undefined;
      let fromStatus = "";
      for (const col of data.columns) {
        const found = col.items.find((c) => c.id === cardId);
        if (found) {
          card = found;
          fromStatus = col.key;
          break;
        }
      }
      if (!card) return;
      // 【H4】同列且落在列空白处（无插入索引）→ 按「移到列尾」处理，符合直觉；
      // 此前是静默 no-op：用户拖了没反应也没提示。
      if (fromStatus === toStatus && toIndex === undefined) {
        const col = data.columns.find((c) => c.key === toStatus);
        if (!col || col.items.length === 0) return;
        toIndex = col.items.length - 1;
        // 本就在列尾 → 真无操作，不发无意义请求。
        if (col.items[toIndex]?.id === cardId) return;
      }

      const snapshot = data; // 回滚快照
      // 【Phase-3 §2.5】携拖拽起点卡片的 updated_at 做乐观并发守卫。
      const expectedUpdatedAt = card.updated_at;

      // 乐观：先从所在列移除该卡，再插入目标列 toIndex（缺省列尾）。
      // 【lifecycle-and-governance §2.8】`total` 也必须跟着乐观调整：列头徽章现在渲染的是
      // 该列**真实总数**而非 items.length（截断列的 items 只是前 100 张），沿用旧 total
      // 会让拖拽后的两列计数在重取落地前一直是错的——又一次「会说谎的 UI」。
      const optimistic: Board<Card> = {
        columns: data.columns.map((col) => {
          const items = col.items.filter((c) => c.id !== cardId);
          const isSource = items.length !== col.items.length;
          if (col.key === toStatus) {
            // 覆盖 status 后整体断言为 Card（联合类型无法逐字段收窄）。
            const moved = { ...card!, status: toStatus } as Card;
            const idx = toIndex == null ? items.length : Math.min(toIndex, items.length);
            return {
              ...col,
              items: [...items.slice(0, idx), moved, ...items.slice(idx)],
              // 同列重排时 isSource 为真，一进一出净变化为 0。
              total: col.total + (isSource ? 0 : 1),
            };
          }
          return { ...col, items, total: col.total - (isSource ? 1 : 0) };
        }),
      };

      // 先落乐观视图（不重新验证），让拖拽手感即时。
      mutate(optimistic, { revalidate: false });

      // 【H3】写入与重取**分两段**处理：此前二者写在同一个 mutate thunk 里，
      // 只要第二步（重取）失败就一并 rollbackOnError，用户看到卡片弹回 + 「移动失败，已回滚」，
      // 而后端其实已经改成功了——是一句彻头彻尾的谎话。
      try {
        await api.patch(`/${entity}/${cardId}/move`, {
          status: toStatus,
          position: toIndex,
          expected_updated_at: expectedUpdatedAt,
        });
      } catch (err) {
        // —— 第一段失败 = 确实没写进去 → 回滚 + 提示（§2.6 错误契约）——
        if (err instanceof ApiError && err.status === 409 && err.allowed) {
          // 状态机 409：非法迁移（体含 allowed）。
          const allowed = err.allowed.length ? `（可迁移至：${err.allowed.join(", ")}）` : "";
          toast.error(`非法状态迁移${allowed}`);
          mutate(snapshot, { revalidate: false });
        } else if (err instanceof ApiError && err.status === 409) {
          // 并发 409：他人已更新（体无 allowed）——拉最新而非回滚到陈旧快照〔§2.5〕。
          toast.error("该工单已被他人更新，请刷新");
          mutate();
        } else if (err instanceof ApiError && err.status === 403) {
          // 【§2.8①】兜底：任何路径下都不再冒出后端的生硬英文 `forbidden`。
          toast.error("你没有权限移动这张工单");
          mutate(snapshot, { revalidate: false });
        } else {
          toast.error(err instanceof ApiError ? err.message : "移动失败，已回滚");
          mutate(snapshot, { revalidate: false });
        }
        return;
      }

      // 【version-plan-console §3.2 落点④】写入**已经成功**这个事实一成立就失效层级视图。
      // 挂在这里而不是第二段重取之后：第二段失败会走上面 catch 之外的另一条分支
      // （`toast.error("已提交，正在刷新")`），那时后端已经改完了，却永远执行不到
      // 重取之后的那一行——版本 / 计划进度就此永久陈旧，而用户看到的提示是「已提交，
      // 正在刷新」，更不会去怀疑。判据应当是「写入成功」，而不是「重取也成功」。
      void invalidateHierarchyViews(globalMutate);

      // —— 第二段：拉取权威数据（后端已算好 position）。失败**不回滚**——写入已成功 ——
      try {
        const fresh = await api.get<Board<Card>>(key);
        mutate(fresh, { revalidate: false });
      } catch {
        toast.error("已提交，正在刷新");
        mutate();
      }
    },
    [data, entity, key, mutate, globalMutate, toast]
  );

  return { board: data, error, isLoading, move, mutate };
}
