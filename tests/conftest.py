"""测试夹具。

P0 阶段只覆盖「不依赖外部服务」的部分（配置、响应、加密、JWT、模型定义）。
P1 起再引入数据库夹具。
"""

import pytest

from app.core.config import Settings, get_settings


@pytest.fixture(scope="session")
def settings() -> Settings:
    """读取 `configs/config.yaml` 的全局配置。

    测试直接复用本地配置，但不会真的去连库 —— 单测不依赖外部服务。
    """
    get_settings.cache_clear()
    return get_settings()


@pytest.fixture()
def client():
    """不触发 lifespan 的测试客户端。

    `TestClient` 只有作为上下文管理器使用时才执行 startup/shutdown，
    这里直接实例化，跳过「探活 MySQL / MinIO」那一段 ——
    P0 的单测不需要数据库。
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app()
    return TestClient(app)
