"""头像底色调色板（self-service-registration §2.1 A-3 / 评审 P0-1）。

【为什么下沉到服务层】本函数此前定义在 `routes/auth.py` 文件**末尾**，被
`routes/users.py:11` 以 `from routes.auth import _pick_color` 反向引用；`seed.py` 则
干脆复制了一份调色板常量、靠一句注释维持同步（典型的第二真相）。本轮 `services/bootstrap.py`
也需要它——service→route 的反向依赖会与上面那条 route→route 依赖凑成一个**在应用启动时
必炸的循环导入**（`routes/__init__.py` 先导入 auth，auth 顶部拉 users，users 回头拉
auth 中尚未执行到的 `_pick_color`）。

故把调色板与选色函数一次性收敛到这里：四个调用点（`routes/auth.py`、`routes/users.py`、
`seed.py`、`services/bootstrap.py`）统一改读，服务层不再依赖路由层。
"""

# 暖色系调色板。取值与迁移前逐字节相同——存量用户的头像底色不得因本次重构漂移。
PALETTE = ("#C15F3C", "#3B6EA5", "#6E8B3D", "#8A5A9B", "#C99A2E", "#4B8B8B")


def pick_color(seed: str) -> str:
    """按用户名确定性地选一个头像底色（同名恒得同色，无随机、无状态）。

    Args:
        seed: 任意字符串，通常是 username。

    Returns:
        `#RRGGBB` 形式的 hex 串，恒 ∈ PALETTE。
    """
    return PALETTE[sum(ord(c) for c in seed) % len(PALETTE)]
