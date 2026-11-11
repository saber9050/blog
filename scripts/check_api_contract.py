"""接口契约校对：文档 vs 实际注册。

用法：

    python scripts/check_api_contract.py

退出码 0 表示完全一致；1 表示有差异（可直接用于 CI 门禁）。

为什么需要它：文档和代码是两份平行的真相，靠人眼对一定会漏。
每加一批接口就跑一次，比上线后发现「前端说接口不存在」便宜得多。

**它只校路径与方法**，不校字段。字段级的校验靠 `tests/` 里的用例 ——
那些用例断言了 `staus` / `create_at` / `pageSize` / `git_hub` 这类
历史拼写，路由级别的脚本管不到。
"""

import glob
import os
import re
import sys

# 必须在 import app.* 之前设置：
# `app/main.py` 末尾有模块级的 `app = create_app()`，import 的那一刻就会
# 初始化日志并打一屏启动横幅。用环境变量把日志级别抬到 CRITICAL 压掉。
# 双下划线表示配置层级，对应 config.yaml 的 `log.level`。
os.environ["LOG__LEVEL"] = "CRITICAL"
# debug 模式下日志级别会被强制抬到 DEBUG，这里连 mode 一起切走
os.environ["APP__MODE"] = "release"

# 文档表格里的接口行：| 1 | GET | `/api/v1/xxx` | 可选 | 说明 |
_DOC_ROW = re.compile(r"\|\s*\d*\s*\|\s*(GET|POST|PUT|DELETE|PATCH)\s*\|\s*`([^`]+)`\s*\|")


def collect_from_docs() -> dict[tuple[str, str], str]:
    """从各模块 `api.md` 的表格里抽接口。

    Returns:
        `{(path, method): 模块名}`。
    """
    found: dict[tuple[str, str], str] = {}
    for path in sorted(glob.glob("docs/*/api.md")):
        module = os.path.basename(os.path.dirname(path))
        text = open(path, encoding="utf-8").read()
        for method, api_path in _DOC_ROW.findall(text):
            if "/api/v1" in api_path:
                found[(api_path, method)] = module
    return found


def collect_from_app() -> set[tuple[str, str]]:
    """从 FastAPI 的 OpenAPI schema 里抽实际注册的接口。

    Returns:
        `{(path, method)}`。
    """
    from app.main import create_app

    schema = create_app().openapi()
    result: set[tuple[str, str]] = set()
    for path, methods in schema["paths"].items():
        for method in methods:
            if method.upper() in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
                result.add((path, method.upper()))
    return result


def main() -> int:
    """执行校对并打印报告。

    Returns:
        进程退出码：0 一致，1 有差异。
    """
    doc = collect_from_docs()
    impl = collect_from_app()

    missing = sorted(set(doc) - impl)
    extra = sorted(impl - set(doc))

    print(f"文档 {len(doc)} 条 | 实现 {len(impl)} 条 | 缺 {len(missing)} | 多 {len(extra)}")

    if missing:
        print("\n[文档有、代码无]")
        for path, method in missing:
            print(f"  {method:<7}{path}   [{doc[(path, method)]}]")

    if extra:
        print("\n[代码有、文档无]")
        for path, method in extra:
            print(f"  {method:<7}{path}")

    if missing or extra:
        print("\n契约不一致，请补齐后再提交。")
        return 1

    print("\n契约一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
