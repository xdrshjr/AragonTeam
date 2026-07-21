"""应用配置（§3.2 backend/config.py）。

Phase-2 §2.5-5 / R-07：全字段改 `os.environ.get`，库 URI **沿用既有
`DATABASE_URL`** 环境变量名（不另引 SQLALCHEMY_DATABASE_URI，避免两个冲突开关）。
新增 SEED_ON_STARTUP、LOGIN_MAX_ATTEMPTS，以及测试专用 TestConfig。
MVP 阶段密钥内置默认值便于开箱即用；生产环境应通过环境变量覆盖。
"""
import os
from datetime import timedelta

from sqlalchemy.pool import StaticPool


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # —— 安全密钥（生产务必用环境变量覆盖）——
    SECRET_KEY = os.environ.get("SECRET_KEY", "aragon-dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "aragon-dev-jwt-secret-change-me")

    # JWT 有效期（秒）——默认一天，方便本地开发。
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=_env_int("JWT_ACCESS_TOKEN_EXPIRES", 86400))

    # —— 数据库（沿用既有 DATABASE_URL 名，R-07）——
    _basedir = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(_basedir, "aragon.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # 缓解 SQLite 并发写锁：加大等待超时（§7 风险表）。
    SQLALCHEMY_ENGINE_OPTIONS = {"connect_args": {"timeout": 15}}

    # —— CORS ——
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")

    # —— 登录限流阈值（§2.5-4）——
    LOGIN_MAX_ATTEMPTS = _env_int("LOGIN_MAX_ATTEMPTS", 10)

    # —— 启动时是否 seed（测试关闭并自建 fixture，§2.5-5）——
    SEED_ON_STARTUP = _env_bool("SEED_ON_STARTUP", True)

    # —— 启动时是否解开崩溃残留的 Agent busy 软锁（data-persistence §2.4）——
    # 真开关：应用内一律读 `app.config["RELEASE_STALE_LOCKS_ON_STARTUP"]`。
    # 多 worker 部署下必须置 false（升级判据见 services/persistence.py 模块 docstring）。
    RELEASE_STALE_LOCKS_ON_STARTUP = _env_bool("RELEASE_STALE_LOCKS_ON_STARTUP", True)

    # —— 文档管理（ticket-document-management §5.3）——
    # blob 根目录。多机部署必须共享该目录（NFS / 对象存储），否则一台机上传的
    # 文件另一台读不到（spec §8 R-11）。随 .gitignore 排除，不入库。
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(_basedir, "var", "uploads"))
    MAX_UPLOAD_MB = _env_int("MAX_UPLOAD_MB", 20)
    # Flask 原生闸：在**进入路由之前**拦截超大请求体，超大文件不会被读进进程。
    # 派生值——子类覆盖 MAX_UPLOAD_MB 时必须同步覆盖本项（类体求值一次，不会跟着变）。
    MAX_CONTENT_LENGTH = _env_int("MAX_UPLOAD_MB", 20) * 1024 * 1024
    # 扩展名白名单。**有意不含 html/htm/svg/js**：它们能在同源下执行脚本，
    # 而 inline 预览路径上这是唯一真正生效的一道防线（spec §8 R-2）。
    DOC_ALLOWED_EXTENSIONS = tuple(
        e.strip().lower()
        for e in os.environ.get(
            "DOC_ALLOWED_EXTENSIONS",
            "md,txt,log,csv,json,yaml,yml,pdf,png,jpg,jpeg,gif,webp,"
            "doc,docx,xls,xlsx,ppt,pptx,zip",
        ).split(",")
        if e.strip()
    )
    # 阶段文档门禁。默认关闭：默认强制会让存量数据全线卡死，且 Agent 流水线会静默死锁。
    DOC_STAGE_GATE = _env_bool("DOC_STAGE_GATE", False)
    # blob 回收宽限窗口（秒）。与去重命中时的 os.utime 配对，关闭「删除↔去重」竞态。
    BLOB_GRACE_SECONDS = _env_int("BLOB_GRACE_SECONDS", 3600)
    # 文本预览 / 在线编辑上限。**前者必须严格大于后者**（doc_policy 启动期断言）：
    # 否则可编辑大小的文件会被截断后保存，截断即成为新版本的全部内容。
    DOC_TEXT_PREVIEW_MAX_BYTES = _env_int("DOC_TEXT_PREVIEW_MAX_BYTES", 1048576)
    DOC_TEXT_EDIT_MAX_BYTES = _env_int("DOC_TEXT_EDIT_MAX_BYTES", 524288)
    # 单次改版最多向多少张单扇出 Activity + 通知；超出只写一条汇总（SQLite 单写者）。
    DOC_FANOUT_MAX_LINKS = _env_int("DOC_FANOUT_MAX_LINKS", 20)

    # —— 文档全流程纵深（document-lifecycle-depth §5.3）——
    # Agent 交付物归档总开关；关掉即完全回到上一轮行为。
    # 【运维注记】它是本轮唯一一个「升级即生效、且会自动产生用户可见数据」的开关。
    # 默认 True 是对的（否则这根支柱等于没上线），但**首次上线建议先以
    # DOC_AGENT_ARCHIVE=false 跑一轮**，确认 LLM 产物质量与 ARCHIVE_KIND 的归类
    # 符合预期后再打开。
    DOC_AGENT_ARCHIVE = _env_bool("DOC_AGENT_ARCHIVE", True)
    # 短于此长度的 Agent 产物不值得建成一份「交付物」。
    DOC_AGENT_ARCHIVE_MIN_CHARS = _env_int("DOC_AGENT_ARCHIVE_MIN_CHARS", 200)
    # 回收站保留期（天）。**运行时不据此自动删任何东西**——只有 tools/purge_trash.py
    # 在人按下 --apply 时读它。本项目没有调度器，不可逆操作应当由人按下。
    DOC_TRASH_RETENTION_DAYS = _env_int("DOC_TRASH_RETENTION_DAYS", 30)

    # —— 根管理员（self-service-registration §2.1）——
    # 【为什么放配置而不是库】它是「所有管理员都进不来」时唯一的破窗入口：
    # 改环境变量 + 重启 = 恢复。放库里就没有这条恢复路径。
    ROOT_ADMIN_USERNAME = os.environ.get("ROOT_ADMIN_USERNAME", "admin")
    ROOT_ADMIN_PASSWORD = os.environ.get("ROOT_ADMIN_PASSWORD", "admin123")
    ROOT_ADMIN_EMAIL = os.environ.get("ROOT_ADMIN_EMAIL", "admin@aragon.dev")
    ROOT_ADMIN_DISPLAY_NAME = os.environ.get("ROOT_ADMIN_DISPLAY_NAME", "Ada（管理员）")
    # 启动期是否执行根管理员保障。**测试环境与三个运维 CLI 必须关**
    # （关闭清单五处见 spec §2.1 A-3′；漏关会让 CLI 往目标库写用户行）。
    ROOT_ADMIN_BOOTSTRAP = _env_bool("ROOT_ADMIN_BOOTSTRAP", True)
    # 是否在每次启动时把库内密码重置回配置值。**默认 false**：默认 true 会让
    # 「根管理员在 /settings 改了密码 → 重启后被环境变量悄悄改回去」，是静默数据丢失。
    # 置 true 是唯一的忘密码恢复流程，但**四步顺序不可换**：
    #   1) 设 true  2) 重启（此刻库内口令 = 配置口令）  3) 用配置口令登录
    #   4) **先把 flag 设回 false 并再重启一次**，之后才去 /settings 改新密码。
    # 把第 4 步的两半颠倒（先改密码、后关 flag）会让新密码在下一次重启时被静默改回旧值——
    # 那正是本 flag 默认 false 所要防的事，只是延后了一次重启。
    # 为让这条流程不可能被忘记：flag 为真时 ensure_root_admin **每次启动都打 warning**。
    ROOT_ADMIN_SYNC_PASSWORD = _env_bool("ROOT_ADMIN_SYNC_PASSWORD", False)

    # —— 自助注册（self-service-registration §2.2）——
    # 邀请码 / 开关 / 默认角色的**兜底默认值**；库内 app_settings 有行时以库为准。
    REGISTRATION_INVITE_CODE = os.environ.get("REGISTRATION_INVITE_CODE", "aragon")
    REGISTRATION_ENABLED = _env_bool("REGISTRATION_ENABLED", True)
    # 【R-16】本项**不是**最终真相：get_registration_settings() 会无条件把它过一遍
    # SIGNUP_ROLES 白名单。否则 `REGISTRATION_DEFAULT_ROLE=admin` 一个环境变量就能让
    # 任何拿到邀请码的人注册即为管理员——白名单只挡了 PATCH 端点，挡不住配置兜底路径。
    REGISTRATION_DEFAULT_ROLE = os.environ.get("REGISTRATION_DEFAULT_ROLE", "member")
    # 5 分钟窗口内单个客户端的注册尝试上限（成功与失败都计数）。
    SIGNUP_MAX_ATTEMPTS = _env_int("SIGNUP_MAX_ATTEMPTS", 10)
    # 【R-14】信任几层反向代理的 X-Forwarded-For。**默认 0 = 一个都不信**，
    # 即 ratelimit.client_ip() 恒等于 request.remote_addr，与今天的 /login 行为逐字节相同。
    # 本仓库自带 nginx 反代模板（ops/templates/aragonteam-nginx-http），在那种部署下
    # remote_addr 恒为 127.0.0.1，限流会退化成**全站单桶**；此时必须置 1。
    # 选「显式配置」而不是无脑接 ProxyFix：无条件信任转发头等于把限流键交给客户端伪造。
    TRUST_PROXY_COUNT = _env_int("TRUST_PROXY_COUNT", 0)

    # —— SQLite 落盘同步级别（data-persistence §2.3，评审 P1-3）——
    # 【文档性镜像，不是 PRAGMA 的读取源】PRAGMA 由 extensions.py 的全局 connect
    # 监听器设置，那里没有 Flask 上下文，只能读 os.environ。本字段只服务
    # README 表格与人工排查；**改这里不会让 PRAGMA 有任何变化**，要改请设环境变量。
    SQLITE_SYNCHRONOUS = os.environ.get("SQLITE_SYNCHRONOUS", "NORMAL")


class TestConfig(Config):
    """pytest 专用（§2.5-5 / R-02）。内存库 + 固定连接池 + 关 seed + 快过期 + 低限流阈。"""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # 【R-02】内存库必须显式固定连接池：整个进程共用同一条连接，
    # 让建表与请求共享连接、表恒可见，规避跨线程 / xdist 的 `no such table`。
    # 覆盖 base 的 connect_args={"timeout":15}（内存库无需 busy-timeout）。
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    SEED_ON_STARTUP = False
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=30)
    # 阈值调小以便快测 429（【R-03】计数随 app 实例重建，见 services/ratelimit.py）。
    LOGIN_MAX_ATTEMPTS = 3
    # 【ticket-document-management §5.3】上限调到 1 MB，让 413 用例只需造 1 MB 数据。
    # MAX_CONTENT_LENGTH 是**派生值**，父类在类体里求值一次，必须在这里一并覆盖。
    MAX_UPLOAD_MB = 1
    MAX_CONTENT_LENGTH = 1 * 1024 * 1024
    # 【document-lifecycle-depth §5.3】测试环境显式关闭 Agent 归档。`from_llm` 判据
    # （`_llm_active()` 在 TESTING 下恒 False）已经保证它不触发，配置层再钉一道，
    # 让「归档相关用例」可以通过 monkeypatch 精确开启，而不必担心某天有人放宽了
    # `_llm_active()` 就静默改变了另外 500 条用例的行为。
    DOC_AGENT_ARCHIVE = False
    # 【self-service-registration §2.1 A-1 · 必须关】若启动期自动建根管理员，users 表在
    # 每个用例开始时就多一行，`GET /api/users` 的长度断言、active_admin_count 断言、
    # 末任管理员 409 用例会**成批失败**。需要根管理员的用例由 conftest 的 root_admin
    # fixture 显式调用 ensure_root_admin。
    # 注意：关 bootstrap 的地方不止这一处——conftest 的 file_app 基类是 Config 而非
    # TestConfig，三个运维 CLI 亦然（关闭清单共五处，见 spec §2.1 A-3′）。
    ROOT_ADMIN_BOOTSTRAP = False
    # 阈值调小以便用 4 次请求测出 429（与 LOGIN_MAX_ATTEMPTS=3 同一手法）。
    SIGNUP_MAX_ATTEMPTS = 3
    # **UPLOAD_DIR 有意不在这里写死**：TestConfig 是类级常量，全套用例共享一份，
    # 写死就等于所有用例共用一个目录。由 conftest 的 app fixture 逐用例注入 tmp_path。
