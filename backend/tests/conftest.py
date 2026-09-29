"""pytest 公共配置：测试数据库隔离、上传目录隔离（设计文档 8.1 #8 测试数据可隔离）。"""
import os
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 独立测试数据库，不污染开发数据
_TEST_DB = BACKEND_DIR / "data" / "test_resume.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    """上传文件写入临时目录，不在仓库留下测试残留。"""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr("app.services.storage.UPLOAD_DIR", d)
    return d


@pytest.fixture()
def sample_resume_text() -> str:
    return """张三
电话：13812345678
邮箱：zhangsan@example.com
求职意向：后端开发工程师（杭州）

教育背景
浙江大学 计算机科学与技术 本科 2020.09-2024.06
主修课程：数据结构、操作系统、计算机网络

实习经历
字节跳动科技有限公司 后端开发实习生 2023.06-2023.12
负责订单服务接口开发，使用 Python 与 MySQL
参与压测与线上问题排查，累计处理工单 50+ 单

项目经历
分布式秒杀系统 核心开发 2023.03-2023.05
设计库存扣减方案，QPS 从 800 提升到 3000
使用 Redis 缓存热点数据，接口耗时下降 60%

专业技能
熟练掌握 Python、Java、MySQL
熟悉 Redis、Docker、Linux 常用命令

荣誉奖项
校级优秀学生奖学金（2022）
全国大学生程序设计竞赛省二等奖

个人爱好广泛，喜欢阅读与跑步，保持每周三次运动习惯。
"""
