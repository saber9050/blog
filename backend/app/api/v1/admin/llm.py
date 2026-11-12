"""AI 模型配置的后台接口（6 条）。

第 7 条「生成摘要」挂在 `/admin/articles/generate-summary`，
注册在 `AdminArticleController` 里（保证路由顺序），实现委托给本模块的 service。
"""

from fastapi import APIRouter, Depends

from app.core.deps import get_llm_service, require_admin
from app.core.response import ResponseBuilder
from app.schemas.llm import (
    LLMConfigCreateRequest,
    LLMConfigUpdateRequest,
    LLMTestRequest,
)
from app.services.llm_service import LLMService


class AdminLLMController:
    """模型配置管理。整组要求管理员。"""

    def __init__(self) -> None:
        """构造并注册路由。"""
        self.router = APIRouter(
            prefix="/admin/llm-configs",
            tags=["后台-AI 模型"],
            dependencies=[Depends(require_admin)],
        )
        self._register_routes()

    def _register_routes(self) -> None:
        """挂载路由。

        `/test` 是静态路径，`/{config_id}` 是动态路径 ——
        **`/test` 必须注册在前面**，否则 `POST /test` 会被
        `POST /{config_id}` 吃掉（虽然这里没有 POST /{id}，但保持习惯）。
        """
        r = self.router
        r.add_api_route("", self.list_configs, methods=["GET"], summary="配置列表")
        r.add_api_route("", self.create_config, methods=["POST"], summary="新建配置")
        # 静态路径（必须在 {config_id} 之前）
        r.add_api_route("/test", self.test_connection, methods=["POST"], summary="测试连接")
        r.add_api_route("/{config_id}", self.get_config, methods=["GET"], summary="配置详情")
        r.add_api_route("/{config_id}", self.update_config, methods=["PUT"], summary="更新配置")
        r.add_api_route("/{config_id}", self.delete_config, methods=["DELETE"], summary="删除配置")

    async def list_configs(
        self,
        service: LLMService = Depends(get_llm_service),
    ):
        """全部配置。`data` 是数组，不分页（配置条数极少）。"""
        result = await service.list_all()
        return ResponseBuilder.ok(result)

    async def get_config(
        self,
        config_id: int,
        service: LLMService = Depends(get_llm_service),
    ):
        """单条配置。"""
        result = await service.get(config_id)
        return ResponseBuilder.ok(result)

    async def test_connection(
        self,
        req: LLMTestRequest,
        service: LLMService = Depends(get_llm_service),
    ):
        """测试连接。

        **成功和失败都返回 200**，前端按 `data.ok` 判断。
        连不通是预期结果，用 500 会让前端的全局拦截器弹错误框。
        """
        result = await service.test(req)
        return ResponseBuilder.ok(result)

    async def create_config(
        self,
        req: LLMConfigCreateRequest,
        service: LLMService = Depends(get_llm_service),
    ):
        """新建配置。先测连接，通过了才入库。"""
        result = await service.create(req)
        return ResponseBuilder.ok(result)

    async def update_config(
        self,
        config_id: int,
        req: LLMConfigUpdateRequest,
        service: LLMService = Depends(get_llm_service),
    ):
        """更新运行参数（不改 base_url / api_key / model）。"""
        await service.update(config_id, req)
        return ResponseBuilder.ok(None)

    async def delete_config(
        self,
        config_id: int,
        service: LLMService = Depends(get_llm_service),
    ):
        """删除配置（物理删除）。"""
        await service.delete(config_id)
        return ResponseBuilder.ok(None)
