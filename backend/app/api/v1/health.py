"""健康检查。

这个接口的响应**不使用统一响应结构**，是照抄 Go 版的既有契约：

    {"status": "ok", "message": "blog-project API is running"}

Docker healthcheck、CI 部署探活、Nginx upstream 检测都直接读 `status`，
换成 `{code, message, data}` 会让这些脚本全部失效。

> 文案在 v2 里改了：Go 版返回的是 `core-coach API is running`，
> 那是项目从另一个叫 core-coach 的工程复制过来的残留（连带环境变量前缀、
> MinIO 路径都是它的名字）。前端与运维脚本都没有引用这条文案，
> 只读 `status` 字段，所以改掉是安全的。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health", summary="健康检查")
async def health() -> JSONResponse:
    """探活。

    只证明**进程活着**，不检查 MySQL / Redis / MinIO 的连通性。
    原因：依赖故障时如果这里返回 5xx，Docker 会判定容器不健康并反复重启，
    结果是「数据库抖了一下，整个站点被重启十次」，反而放大故障。

    Returns:
        `{"status": "ok", "message": "..."}`，固定 200。
    """
    return JSONResponse(
        status_code=200,
        content={
            "status": "ok",
            "message": "blog-project API is running",
        },
    )
