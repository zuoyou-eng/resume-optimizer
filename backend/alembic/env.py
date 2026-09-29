"""Alembic 迁移环境。

与 app/database.py 的关系：
- app/database.py 的 Base.metadata 是 schema 的唯一真源（ORM 模型）
- 本文件负责把 metadata 的变更转成迁移脚本，并执行迁移
- 测试仍走 Base.metadata.create_all（隔离、快速），由 test_migrations.py
  校验"迁移后的 schema 与 metadata 一致"，防止两个真源漂移
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.database import Base
from app import models  # noqa: F401  确保所有模型已注册到 metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 数据库连接从应用配置读取，不依赖 alembic.ini（避免两处配置不一致）
# 键名必须是 sqlalchemy.url：run_migrations_online 用 engine_from_config(prefix="sqlalchemy.")
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata

# SQLite 无法直接 ALTER TABLE（如加列、改约束），必须用 batch 模式
# （建临时表 → 拷贝 → 改名）。不加这个参数，将来任何改列迁移都会失败。
_IS_SQLITE = settings.is_sqlite


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL 不连接数据库（供人工审查 / DBA 执行）。"""
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_IS_SQLITE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库并执行迁移。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_IS_SQLITE,
            # PostgreSQL 上按 schema 比较；SQLite 不需要
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
