// version-plan-console：版本 / 计划（「项目 → 版本 → 计划 → 需求/BUG」四层树的中间两层）。
//
// 【为什么不住在 lib/types.ts 里】设计（§4.2）本来要求把这些类型追加到 `lib/types.ts` 的
// 「工单域 / 文档域接缝处」，但那个文件加完就是 825 行，越过 CLAUDE.md 记在
// `.claude-index/config.md` 里的 `MAX_FILE_LINES: 800` 硬阈值，而该规则的处置逐字是
// 「超过即按职责拆分到新模块」。故本模块只搬走这一个自足的域，**并由 `lib/types.ts`
// 原样 `export *` 出去**——设计里写的 `import type { Version } from "@/lib/types"`
// 因此逐字仍然成立，没有任何调用点需要知道这次拆分。
//
// 注意：`Version` 与 `lib/types.ts` 里的 `DocumentVersion`（文档改版历史）是**完全不同
// 的概念**，勿混。两个状态枚举与后端 `models/{version,plan}.py` 的 `*_STATUSES` 逐字一致，
// 且**不是同一个集合**（版本有 released、计划有 completed）——把版本状态发给
// `/plans?status=` 是 **400**，不是「筛不出东西」。

export type VersionStatus = "planning" | "active" | "released" | "archived";
export type PlanStatus = "planning" | "active" | "completed" | "archived";

export interface Version {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  status: VersionStatus;
  /** DATE，形如 "2026-08-01"，**无** Z 后缀（models/version.py 的 _iso_date）。 */
  target_date: string | null;
  /** 服务端托管：随 status 进出 released 由后端 stamp / 清空，**前端永不发送**。 */
  released_at: string | null;
  owner_id: number | null;
  position: number;
  created_at: string;
  updated_at: string;
  plan_count: number;
  /** 该版本下**全部计划**名下的工单数（后端两跳聚合，`routes/versions._serialize_many`）。
   *  **前端不得自行对 plans 列表求和**——它是分页的，客户端求和必然漏算。 */
  total_count: number;
  done_count: number;
}

export interface Plan {
  id: number;
  version_id: number;
  /** 反范式冗余，恒等于所属版本的 project_id（models/plan.py）。 */
  project_id: number;
  name: string;
  description: string | null;
  status: PlanStatus;
  start_date: string | null;
  end_date: string | null;
  position: number;
  created_at: string;
  updated_at: string;
  /** 富化字段（routes/plans._serialize_many），恒存在。 */
  requirement_count: number;
  bug_count: number;
  done_count: number;
}

/** 工单上挂载的只读计划概要（services/hierarchy._plan_context_map）。
 *  `version_name` 可为 null——版本行已不存在时的防御值。 */
export interface PlanContext {
  id: number;
  name: string;
  version_id: number;
  version_name: string | null;
}

/** POST /api/versions。project_id 必填且创建后不可变。 */
export interface VersionCreate {
  name: string;
  project_id: number;
  description?: string;
  status?: VersionStatus;
  owner_id?: number | null;
  target_date?: string | null;
}

/** PATCH /api/versions/:id。**故意不含** project_id 与 released_at：前者被后端静默忽略、
 *  后者服务端托管——放进类型等于邀请调用方去发一个永远不生效的字段。 */
export interface VersionUpdate {
  name?: string;
  description?: string;
  status?: VersionStatus;
  owner_id?: number | null;
  target_date?: string | null;
  position?: number;
}

export interface PlanCreate {
  name: string;
  version_id: number;
  description?: string;
  status?: PlanStatus;
  start_date?: string | null;
  end_date?: string | null;
}

export interface PlanUpdate {
  name?: string;
  description?: string;
  status?: PlanStatus;
  start_date?: string | null;
  end_date?: string | null;
  /** 允许改挂版本，但必须同项目，否则后端 400。 */
  version_id?: number;
  position?: number;
}
