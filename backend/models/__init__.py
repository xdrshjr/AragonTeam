"""模型汇总导出（§3.2 backend/models/__init__.py）。

在 db.create_all() 之前必须先 import 全部模型，表才会注册到 metadata。
app.py 通过 `import models` 触发本模块，从而一次性加载所有表定义。
"""
from .user import User, ROLES, USER_SOURCES
from .app_setting import AppSetting
from .agent import Agent, AGENT_KINDS, AGENT_STATUSES
from .project import Project
from .requirement import Requirement, PRIORITIES, ASSIGNEE_TYPES
from .bug import Bug, SEVERITIES
from .activity import (
    Activity, ENTITY_TYPES, TICKET_ENTITY_TYPES, ACTOR_TYPES, APP_SETTING_ENTITY_ID,
)
from .comment import Comment, COMMENT_AUTHOR_TYPES, COMMENT_ENTITY_TYPES
from .notification import Notification, NOTIFICATION_TYPES
from .notification_preference import NotificationPreference
from .seed_record import SeedRecord, SEED_VERSION, SEED_ENTITY_TYPES
from .document import (
    Document, DocumentVersion, DOCUMENT_KINDS, DOCUMENT_KIND_LABELS,
)
from .document_link import DocumentLink, DOCUMENT_LINK_ENTITY_TYPES

__all__ = [
    "User", "ROLES", "USER_SOURCES",
    # 【self-service-registration §3.2】import 行与本列表**两处都要登记**（同 Document 的教训）。
    "AppSetting",
    "Agent", "AGENT_KINDS", "AGENT_STATUSES",
    "Project",
    "Requirement", "PRIORITIES", "ASSIGNEE_TYPES",
    "Bug", "SEVERITIES",
    # 【account-security-and-governance §3.2 / 评审 P2-3】新增的两个符号同样两处登记：
    # 本仓库的符号再导出约定，不登记就是一个新孤岛（CLAUDE.md 评审清单第 8 条）。
    "Activity", "ENTITY_TYPES", "TICKET_ENTITY_TYPES", "ACTOR_TYPES",
    "APP_SETTING_ENTITY_ID",
    "Comment", "COMMENT_AUTHOR_TYPES", "COMMENT_ENTITY_TYPES",
    "Notification", "NOTIFICATION_TYPES",
    "NotificationPreference",
    "SeedRecord", "SEED_VERSION", "SEED_ENTITY_TYPES",
    # 【ticket-document-management §3.2 / 评审 R20】import 行与本列表**两处都要登记**：
    # 漏前者表不进 metadata（create_all 建不出来），漏后者名字导不出。
    "Document", "DocumentVersion", "DOCUMENT_KINDS", "DOCUMENT_KIND_LABELS",
    "DocumentLink", "DOCUMENT_LINK_ENTITY_TYPES",
]
