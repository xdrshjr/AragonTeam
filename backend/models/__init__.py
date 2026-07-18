"""模型汇总导出（§3.2 backend/models/__init__.py）。

在 db.create_all() 之前必须先 import 全部模型，表才会注册到 metadata。
app.py 通过 `import models` 触发本模块，从而一次性加载所有表定义。
"""
from .user import User, ROLES
from .agent import Agent, AGENT_KINDS, AGENT_STATUSES
from .project import Project
from .requirement import Requirement, PRIORITIES, ASSIGNEE_TYPES
from .bug import Bug, SEVERITIES
from .activity import Activity, ENTITY_TYPES, ACTOR_TYPES
from .comment import Comment, COMMENT_AUTHOR_TYPES, COMMENT_ENTITY_TYPES

__all__ = [
    "User", "ROLES",
    "Agent", "AGENT_KINDS", "AGENT_STATUSES",
    "Project",
    "Requirement", "PRIORITIES", "ASSIGNEE_TYPES",
    "Bug", "SEVERITIES",
    "Activity", "ENTITY_TYPES", "ACTOR_TYPES",
    "Comment", "COMMENT_AUTHOR_TYPES", "COMMENT_ENTITY_TYPES",
]
