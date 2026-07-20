"""文档服务门面（ticket-document-management §3.1）。

路由层只 import 这里，不直接 import 子模块——`storage.py` 是唯一接触文件系统的模块，
未来切到对象存储时替换面就只有它一个，门面让这件事在调用方无感。
"""
from services.documents import counts, mime, service, storage
from services.documents.storage import BlobMissing, StorageUnavailable

__all__ = [
    "counts", "mime", "service", "storage",
    "BlobMissing", "StorageUnavailable",
]
