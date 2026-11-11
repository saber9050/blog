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


@pytest.fixture(scope="module")
def live_client():
    """会触发 lifespan 的测试客户端（连库、建管理员）。

    关键点：**清空 SMTP 配置**。
    本地 `configs/config.yaml` 里填了真实的 QQ 邮箱授权码，
    不清空的话，测试里发验证码会真的往外发信 ——
    收件人是 `xxx@example.com` 这种不存在的域名，QQ 服务器直接拒绝，
    接口返回 500，测试全红。而且真发信会消耗发信配额。

    清空后 `EmailSender` 在 debug 模式下降级为「只打日志」，
    流程照样跑通，还不产生任何外部副作用。
    """
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from app.core.config import get_settings
    from app.main import create_app

    settings = get_settings().model_copy(deep=True)
    settings.smtp.username = ""
    settings.smtp.password = SecretStr("")

    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
