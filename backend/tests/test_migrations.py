"""Alembic 迁移测试。

核心是 test_migration_matches_orm_metadata：项目里有两处能建表——
ORM 的 Base.metadata.create_all（测试用）和 Alembic 迁移（部署用）。
如果只改模型不生成迁移，两者会静默分叉：测试全绿但生产库缺列。
这个测试把"Alembic 迁移后的 schema"与"ORM 元数据"逐项比对，差异必须为空。
"""
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.command import downgrade, upgrade
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.config import settings
from app.database import Base
from app import models  # noqa: F401  注册全部模型

BACKEND_DIR = Path(__file__).resolve().parent.parent
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


def _migrated_schema(tmp_path) -> Path:
    """在独立临时库上执行 alembic upgrade head，返回库路径。"""
    db = tmp_path / "migrated.db"
    url = f"sqlite:///{db.as_posix()}"
    # env.py 会从 settings.DATABASE_URL 读连接并覆盖外部配置，故必须 patch 它
    original = settings.DATABASE_URL
    settings.DATABASE_URL = url
    try:
        upgrade(Config(str(ALEMBIC_INI)), "head")
    finally:
        settings.DATABASE_URL = original
    return db


def test_alembic_ini_exists() -> None:
    """迁移配置必须在位，否则部署无从执行迁移。"""
    assert ALEMBIC_INI.is_file(), "backend/alembic.ini 缺失"
    versions = BACKEND_DIR / "alembic" / "versions"
    assert versions.is_dir(), "backend/alembic/versions 缺失"
    assert list(versions.glob("*.py")), "没有任何迁移脚本"


def test_migration_matches_orm_metadata(tmp_path) -> None:
    """迁移建出的 schema 必须与 ORM 元数据完全一致（防双真源漂移）。"""
    db = _migrated_schema(tmp_path)
    mig_engine = create_engine(f"sqlite:///{db.as_posix()}")
    try:
        with mig_engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            diffs = compare_metadata(ctx, Base.metadata)
        # 过滤掉与 ORM 无关的系统表差异
        diffs = [d for d in diffs if "alembic_version" not in str(d)]
        assert diffs == [], f"迁移与 ORM 元数据存在 {len(diffs)} 处差异：\n" + "\n".join(map(str, diffs))
    finally:
        mig_engine.dispose()


def test_migration_creates_all_tables(tmp_path) -> None:
    """迁移必须建出全部业务表（含 ORM 里声明的每一张）。"""
    import sqlite3

    db = _migrated_schema(tmp_path)
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        }
    finally:
        conn.close()
    expected = set(Base.metadata.tables.keys())
    missing = expected - tables
    assert not missing, f"迁移缺少表：{missing}"
    # alembic_version 是 Alembic 自己的版本表
    assert "alembic_version" in tables


def test_migration_is_reversible(tmp_path) -> None:
    """迁移必须可回滚：downgrade 后业务表全部消失。"""
    db = _migrated_schema(tmp_path)
    url = f"sqlite:///{db.as_posix()}"
    original = settings.DATABASE_URL
    settings.DATABASE_URL = url
    try:
        downgrade(Config(str(ALEMBIC_INI)), "base")
    finally:
        settings.DATABASE_URL = original

    import sqlite3

    conn = sqlite3.connect(str(db))
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
            )
        }
    finally:
        conn.close()
    # 回滚后只剩 Alembic 版本表（业务表全部删除）
    assert not (tables - {"alembic_version"}), f"回滚后残留表：{tables - {'alembic_version'}}"


def test_migration_is_idempotent(tmp_path) -> None:
    """重复执行 upgrade 不应报错（已是最新版本时是 no-op）。"""
    db = _migrated_schema(tmp_path)
    url = f"sqlite:///{db.as_posix()}"
    original = settings.DATABASE_URL
    settings.DATABASE_URL = url
    try:
        upgrade(Config(str(ALEMBIC_INI)), "head")  # 第二次升级
    finally:
        settings.DATABASE_URL = original
    # 能跑到底即通过；再确认表仍在
    import sqlite3

    conn = sqlite3.connect(str(db))
    try:
        n = len(
            list(
                conn.execute(
                    "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
                )
            )
        )
    finally:
        conn.close()
    assert n == len(Base.metadata.tables) + 1  # 业务表 + alembic_version


def test_migration_supports_postgresql_variant() -> None:
    """JSONB/JSON 双兼容必须在迁移里保留（部署 PG 时不能退化成 TEXT）。"""
    versions = BACKEND_DIR / "alembic" / "versions"
    source = "\n".join(p.read_text(encoding="utf-8") for p in versions.glob("*.py"))
    n_jsonb = source.count("postgresql.JSONB")
    n_variant = source.count("with_variant")
    assert n_jsonb > 0, "迁移缺少 PostgreSQL JSONB 定义"
    # 每个 JSONB 列都必须带 with_variant，否则 SQLite 上类型不兼容
    assert n_jsonb == n_variant, (
        f"有 {n_jsonb} 个 JSONB 列但只有 {n_variant} 处 with_variant，存在未做双兼容的列"
    )
