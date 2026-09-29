"""Dockerfile：后端 FastAPI 服务（设计文档第 10 章部署架构）。"""
FROM python:3.11-slim

WORKDIR /app

# 系统依赖：psycopg2 编译与 PDF 处理所需
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-pg.txt .
# requirements-pg.txt 单独安装：psycopg2 需要 libpq-dev/build-essential 才能编译，
# 这两个文件在上一步已装好。拆开的目的是让本地开发（SQLite）不必装它——
# Python 3.14 上没有预编译 wheel，放进默认依赖会挡住"只想本地跑起来"的人。
RUN pip install --no-cache-dir -r requirements.txt -r requirements-pg.txt

COPY app ./app
# 迁移文件必须一并进镜像：启动时要执行 alembic upgrade head，
# 只 COPY app 会导致容器内找不到 alembic.ini / alembic/versions（启动即失败）
COPY alembic.ini .
COPY alembic ./alembic

# 数据目录（SQLite 场景）与上传目录使用卷持久化
RUN mkdir -p /app/data/uploads
VOLUME ["/app/data"]

EXPOSE 8000

# 先执行数据库迁移再启动服务。
# 设计取舍：不用 create_all——表结构由 Alembic 迁移版本化管理，
# 将来升级只需新增迁移文件，不依赖"删库重建"。
# alembic 失败会以非零码退出，容器随之停止，不会带病启动。
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
