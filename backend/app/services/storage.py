"""文件存储：本地文件系统（开发）→ MinIO（部署），接口一致便于迁移（设计文档第 2 章）。"""
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import UPLOAD_DIR


def save_upload(filename: str, content: bytes) -> tuple[str, Path]:
    """保存上传文件，返回 (相对路径, 绝对路径)。按日期分目录。"""
    date_dir = datetime.now(timezone.utc).strftime("%Y%m%d")
    ext = Path(filename).suffix.lower()
    rel_name = f"{uuid.uuid4().hex}{ext}"
    rel_path = f"{date_dir}/{rel_name}"
    abs_path = UPLOAD_DIR / date_dir / rel_name
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(content)
    return rel_path, abs_path


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
