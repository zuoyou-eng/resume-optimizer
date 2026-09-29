"""数据库连接与会话管理。

设计文档第 2 章选型 PostgreSQL 14（JSONB 存解析结果）。
JsonType 使用 with_variant：在 PostgreSQL 上为 JSONB，在 SQLite 上为 JSON，
同一份模型代码两种数据库通用——本地验证零依赖，部署时无缝切换。
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import JSON
from sqlalchemy.dialects.postgresql import JSONB

from app.config import settings

# PostgreSQL 用 JSONB，SQLite 用 JSON（类型变体，无需改动模型）
JsonType = JSONB().with_variant(JSON(), "sqlite")

if settings.is_sqlite:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},  # FastAPI 多线程访问 SQLite 需要
        echo=False,
    )
else:
    engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI 依赖：每请求一个会话，用完即关。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """建表（仅用于本地开发/测试的快捷路径）。

    部署路径请使用 Alembic 迁移：
        alembic upgrade head
    表结构的唯一权威版本在 backend/alembic/versions/，容器启动时自动执行
    （见 backend/Dockerfile 的 CMD）。tests/test_migrations.py 会校验
    "迁移后的 schema 与本函数的 create_all 结果一致"，防止两个真源漂移。
    """
    from app import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
