"""看板列内 position 的唯一分配器（bulk-operations §2.2）。

【为什么要单独一个模块】`_next_position` 此前有**两份**逐字相同的实现：
`routes/requirements.py::_next_position` 与 `services/agent_runner.py::_next_position`，
后者的 docstring 明写「与前者同语义，**必须两处同步修改**」——那正是
`services/lifecycle.py` 开篇所说的、不该再复制第三份的反面教材。批量流转是第三个
调用点，与其再抄一遍，不如把它提到一个叶子模块里，两处旧实现改为薄转发。

本模块只依赖 `extensions.db` 与传入的模型类，不 import routes，也不 import 其它
service，因此谁都可以引用它而不产生环依赖。
"""
from sqlalchemy import func

from extensions import db


def next_position(model, status: str, project_id) -> int:
    """返回「同项目同状态」列的下一个 position（该列现有最大值 + 1；空列为 0）。

    position 的语义是**看板某一列内的相对次序**，而看板已按项目过滤（board.py），
    因此编号必须与看板可见集合同域，否则跨项目卡片会污染插入索引（§2.5）。

    Args:
        model: Requirement / Bug 模型类。
        status: 目标状态列。
        project_id: 工单所属项目 id，未归属传 None。**必填**（scale-and-project-scope
            评审 R3：给默认值会让漏传的调用点静默把单编进「未归属」号段）。

    Returns:
        该列的下一个可用 position。
    """
    # 【P2-3】单聚合查询取列内最大 position，不再取回整列行再在 Python 里求 max。
    # 语义逐字节不变：空列 → None → 0。
    current_max = db.session.query(func.max(model.position)).filter_by(
        status=status, project_id=project_id).scalar()
    return (current_max if current_max is not None else -1) + 1
