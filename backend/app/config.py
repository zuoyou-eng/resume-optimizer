"""应用配置：全部通过环境变量注入，避免密钥与路径硬编码（对应设计文档第 10 章）。"""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"


class Settings:
    # 数据库：默认 SQLite（本地开发/验证零依赖），通过环境变量切换 PostgreSQL
    # docker-compose 中会注入 postgresql+psycopg2://...
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{DATA_DIR / 'resume.db'}"
    )

    # 文件上传约束（FR-01）
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
    ALLOWED_EXTENSIONS: set[str] = {
        ext.strip().lower()
        for ext in os.getenv(
            "ALLOWED_EXTENSIONS", ".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp"
        ).split(",")
    }
    EXT_CONTENT_TYPE_MAP: dict[str, str] = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }

    # 图片 OCR（FR-01 图片格式）：调用系统 OCR 引擎的超时上限
    OCR_TIMEOUT_SECONDS: int = int(os.getenv("OCR_TIMEOUT_SECONDS", "90"))

    # 规则版本号：解析规则变更必须升版，保证相同输入可复现（NFR-08）
    RULE_VERSION: str = "rule-1.0.0"

    # 服务信息
    APP_NAME: str = "简历优化助手 API"
    APP_VERSION: str = "0.1.0"

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


settings = Settings()

# 确保数据目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
