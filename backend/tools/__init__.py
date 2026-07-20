"""离线维护脚本包（data-persistence-and-seed-slimming §3）。

存在的意义只是让 `python tools/purge_demo_data.py` 与
`python -m tools.purge_demo_data` 两种调用方式都可用；本包**不导出任何符号**，
也不应被应用运行时 import——这里的脚本都是「人在服务器上手动执行一次」的工具。
"""
