# 07 AI 模型 · 设计方案

> 这是整个重写里**唯一保留的 AI 能力**：一个对话模型 + 一个摘要接口。
> 向量化、切分、检索、多轮会话全部删除，`pgvector` 依赖也一并去掉。

## 1. 职责与边界

**做什么**

- 模型配置的增删改查（存库，后台维护）
- 测试连接（不落库，调用一次 `/chat/completions`）
- 用指定模型为文章生成摘要

**不做什么**

- 不做 embedding（向量功能已删）
- 不做对话、流式、多轮、工具调用、RAG
- 不做失败重试、多模型负载均衡、限流

---

## 2. 目录结构

```
app/
├── api/v1/admin/
│   ├── llm_configs.py                # LLMConfigController（6 条）
│   └── articles.py                   # 其中的 generate-summary（1 条，归本模块实现）
├── services/llm/
│   ├── llm_config_service.py         # LLMConfigService：配置 CRUD + 解析
│   ├── summary_service.py            # SummaryService：摘要生成
│   └── prompt.py                     # 摘要 prompt 常量
├── integrations/
│   └── llm_client.py                 # LLMClient：OpenAI 兼容 HTTP 客户端
├── repositories/llm_config_repository.py
└── schemas/llm.py
```

---

## 3. 类设计

### 3.1 `LLMClient`

```python
class LLMClient:
    """OpenAI 兼容协议客户端，只实现 /chat/completions。

    复用连接：httpx.AsyncClient 内部有连接池，每次请求新建 client 会
    多一次 TLS 握手（调用外部 API 时这几十毫秒很明显）。
    所以 client 实例按「配置指纹」缓存，配置变了才重建 —— 与 Go 版逻辑一致。
    """

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._fingerprint: str = ""

    async def chat(self, cfg: LLMConfig, messages: list[ChatMessage]) -> str:
        """发一次对话请求，返回模型回复文本。

        Args:
            cfg: 解析后的模型配置（含 base_url / api_key / model / 超时等）。
            messages: 消息列表，摘要场景只有一条 user 消息。

        Returns:
            模型返回的纯文本内容。

        Raises:
            BizError: 未配置 key/base_url/model(500)、请求失败(500)、
                      上游返回非 200(500)、响应为空(500)。
        """

    async def test_connection(self, cfg: LLMConfig) -> tuple[str, int]:
        """测试连通性，返回 (回复内容, 耗时毫秒)。

        与 chat 的区别：超时上限 15 秒（测试不该让用户等 30 秒），
        prompt 固定为「请只回复"连接成功"四个字」。
        """

    def _rebuild_if_needed(self, cfg: LLMConfig) -> None:
        """配置指纹变化时重建 client。

        指纹包含 base_url / model / api_key / timeout / max_tokens / temperature，
        任一变化都重建，避免用了旧配置连接池里的旧 header。
        """

    async def close(self) -> None:
        """关闭连接池。lifespan shutdown 时调用。"""
```

### 3.2 `LLMConfigService`

```python
class LLMConfigService:
    """模型配置的增删改查。

    配置存库而不是写配置文件：
      - 部署时不需要重启就换模型
      - api_key 不进 Git
      - 后台可视化测试连接，填错立刻发现
    """

    def __init__(self, repo: LLMConfigRepository, client: LLMClient) -> None: ...

    async def list(self) -> list[LLMConfigResponse]:
        """列出全部配置，密钥脱敏。

        脱敏规则（照抄 Go 的 maskKey）：
          - 空字符串 → ""
          - 长度 ≤ 4 → "****"
          - 其他     → 前 3 位 + "****" + 后 4 位

            sk-1234567890abcdef → sk-****cdef
            abcd                → ****
            abcde               → abc****bcde

        注意前缀是 3 位，长度阈值是 4：长度 ≤4 全部打码，5 位以上才保留前后缀。
        """

    async def get(self, config_id: int) -> LLMConfigResponse: ...

    async def test(self, req: TestConfigRequest) -> TestConnectionResponse:
        """测试连接。

        特殊逻辑：`api_key` 为空且 `id > 0` 时，复用该配置已存的密钥。
        这样用户编辑已有配置时不用重新粘贴 key 也能测。

        返回值永远 200，成功与否看 body 里的 `ok` 字段 ——
        连接失败是预期结果，不该用 HTTP 500 表达。
        """

    async def create(self, req: CreateConfigRequest) -> LLMConfigResponse:
        """新建配置。

        顺序不能反：**先测试连接，通过才入库**。
        反过来的话，测试失败会在库里留一条用不了的记录，还得回滚删除。

        强制 type=1（对话模型）。前端已去掉类型选择，但服务端仍要兜底 ——
        接口是公开的，不能指望调用方守规矩。
        """

    async def update(self, config_id: int, req: UpdateConfigRequest) -> None:
        """更新。

        只允许改运行参数（timeout / max_tokens / temperature）与启用状态。
        base_url / api_key / model **不可改**：换模型等于换配置，应该删了重建。
        """

    async def delete(self, config_id: int) -> None: ...

    async def resolve(self, config_id: int) -> LLMConfig:
        """解析出可用于调用的配置。摘要接口的唯一入口。

        校验链（顺序不能变，错误信息要能指导用户下一步动作）：
          1. 配置存在            → 否则 404「配置不存在」
          2. status == 1         → 否则 400「该模型配置已禁用，请先在「AI 模型」页启用」
          3. type == 1           → 否则 400「该配置是向量模型，不能用于对话生成」

        第 3 条在新库里其实不会触发（不再有向量模型），但保留：
        旧库可能被手工导入过 type=2 的数据。
        """
```

### 3.3 `SummaryService`

```python
class SummaryService:
    """文章摘要生成。

    职责很窄：把文章正文洗干净 → 拼 prompt → 调模型 → 清洗结果。
    不负责保存到数据库 —— 摘要由前端拿到后填进编辑器，用户确认后才随文章一起提交。
    这样用户有修改余地，不会出现「AI 写错了也存进去」。
    """

    def __init__(self, config_service: LLMConfigService, client: LLMClient) -> None: ...

    async def generate(self, req: GenerateSummaryRequest) -> GenerateSummaryResponse:
        """生成摘要。

        Args:
            req: 含 config_id（用哪个模型）、title、content。

        Returns:
            GenerateSummaryResponse: 单字段 summary，已截断到 255 字符。

        Raises:
            BizError: 正文为空(400) / 配置不可用(404/400) / 模型调用失败(500)。
        """

    @staticmethod
    def strip_markup(content: str) -> str:
        """Markdown / HTML → 纯文本。

        必须做，否则 `#` `**` `|` 会原样进 prompt，白占 token 还干扰模型。
        规则：
          - 去掉 HTML 标签
          - 去掉 Markdown 标题标记、强调符号、代码围栏、链接语法（保留链接文字）
          - 连续空白压成单个空格
        """

    @staticmethod
    def truncate(text: str, limit: int) -> str:
        """按字符截断（不是字节）。

        按字节截会把一个汉字切成半个，产生乱码。
        Python 的 str 天然按字符，直接切片即可。
        """
```

---

## 4. 数据模型

### `ai_model_configs`

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | `BIGINT` | PK | |
| `base_url` | `VARCHAR(255)` | NOT NULL | 到 `/v1` 为止，如 `https://api.deepseek.com/v1` |
| `api_key` | `VARCHAR(512)` | NOT NULL | **Fernet 密文**（见 8.1），不是明文 |
| `model` | `VARCHAR(128)` | NOT NULL | 如 `deepseek-chat` |
| `type` | `SMALLINT` | NOT NULL DEFAULT 1 | 恒为 1（对话模型） |
| `timeout_sec` | `INT` | DEFAULT 30 | 单次调用超时 |
| `max_tokens` | `INT` | DEFAULT 2048 | 生成上限 |
| `temperature` | `DOUBLE` | DEFAULT 0.3 | 采样温度 |
| `status` | `SMALLINT` | NOT NULL | 1 启用 / 0 禁用 |
| `created_at` / `updated_at` | `DATETIME` | NOT NULL | |

> **与 Go 版的差异**：
> - 不建 `dimension` 列（只有向量模型用）
> - 不建 `name` 列（Go 注释自己写了「仅为满足历史 not null 约束」）
> - 不建 `pgvector` 相关的唯一索引逻辑（`EnsureSingleEmbeddingModelIndex` 已删除）

---

## 5. 核心流程

### 5.1 测试连接

```
POST /admin/llm-configs/test {base_url, model, api_key?, id?}
 → api_key 为空且 id > 0 → 读库取已存密钥
     └─ 还是空 → 返回 {ok: false, error: "请填写 api_key"}（HTTP 200）
 → 构造临时配置（timeout 上限 15s）
 → POST {base_url}/chat/completions
     body: {model, messages: [{role: user, content: "请只回复\"连接成功\"四个字"}], max_tokens: 32}
     header: Authorization: Bearer {api_key}
 → 成功 → {ok: true, latency_ms: 834, reply: "连接成功"}
 → 失败 → {ok: false, latency_ms: 834, error: "LLM 返回异常状态码 401: Invalid API key"}
```

### 5.2 新建配置

```
POST /admin/llm-configs {base_url, api_key, model, timeout_sec?, max_tokens?, temperature?, status?}
 → 逐项 strip 空格
 → 先 test_connection
     └─ 失败 → 400，错误信息里带上游原因
 → INSERT ai_model_configs(type=1, status=默认 1)
 → 返回脱敏后的配置
```

### 5.3 生成摘要

```
POST /admin/articles/generate-summary {config_id, title, content}
 → 正文清洗：strip_markup(content)
     └─ 结果为空 → 400「文章内容为空」
 → 截断到 8000 字符
 → 拼 prompt（见 5.4）
 → resolve(config_id) 拿配置
 → LLMClient.chat()
 → 结果清洗：
     1. strip()
     2. 去掉首尾的 ASCII 双引号、单引号、直角引号「」
     3. 再 strip()
     4. 截断到 255 字符（summary 列是 VARCHAR(255)，不截会入库报错）
 → 返回 {summary}
```

### 5.4 摘要 Prompt（逐字照抄）

```
请为以下文章生成一段简洁的摘要，要求：
- 不超过100字
- 概括文章核心内容
- 语言简洁通顺
- 不要出现"本文"、"文章"等开头
- 不要出现任何表情符号
- 只输出一段话的文本
- 不要有任何形式的分段和分条回答
- 生成完摘要后审查是否超过了150词，如果超过重新按照要求生成

文章标题：
{title}

文章内容：
{content}

摘要：
```

> 这一串约束看着啰嗦，但每条都对应一个实际出现过的问题：
> 模型爱加表情、爱分点、爱用「本文介绍了」开头。**原样照抄，不要优化**。

---

## 6. 错误码

| 场景 | code | message |
|---|---|---|
| 配置不存在 | 404 | 配置不存在 |
| 配置已禁用 | 400 | 该模型配置已禁用，请先在「AI 模型」页启用 |
| 类型不匹配 | 400 | 该配置是向量模型，不能用于对话生成 |
| 测试失败 | 200 | `{ok: false, error: "..."}` |
| 正文为空 | 400 | 文章内容为空 |
| 模型调用失败 | 500 | LLM 返回异常状态码 401: Invalid API key |
| API Key 未配置 | 500 | LLM API Key 未配置 |

---

## 7. 测试要点

| # | 用例 | 断言 |
|---|---|---|
| 1 | 列表接口 | `api_key` 不出现明文，只有 `api_key_masked` |
| 2 | 测试连接不落库 | 调用后 `ai_model_configs` 行数不变 |
| 3 | 测试时 api_key 留空 + 带 id | 复用已存密钥，能成功 |
| 4 | 新建时上游返回 401 | 400，库里没有新记录 |
| 5 | 摘要：正文纯 Markdown | prompt 里无 `#` `**` |
| 6 | 摘要：正文 2 万字 | 只取前 8000 字符 |
| 7 | 摘要：模型返回带引号 | 输出已去掉首尾引号 |
| 8 | 摘要：模型返回 300 字 | 输出被截到 255 |
| 9 | 摘要：配置被禁用 | 400，提示去启用 |
| 10 | 摘要：`config_id` 不存在 | 404 |
| 11 | 上游超时 30 秒 | 500，错误信息可读，不抛堆栈 |

---

## 8. 开放问题

### 8.1 api_key 存储：本轮 AES 加密

| 方案 | 说明 | 结论 |
|---|---|---|
| A. 明文存 | 与 Go 版一致，DB 泄露即密钥泄露 | 否决 |
| **B. 应用层 AES 加密** | 密钥放 `config.yaml` 的 `security.fernet_key`，库里存密文 | **本轮采用，+0.5 天** |
| C. 走 KMS | 最安全但引入外部依赖 | 不做 |

实现要点：

- 用 `cryptography` 的 `Fernet`（AES-128-CBC + HMAC），比手搓 AES 少踩坑。
- `api_key` 列存**密文**（长度会变长，`VARCHAR(512)` 够用）。
- `resolve()` 取出后解密再传给 `LLMClient`；加解密逻辑集中在 `CryptoBox` 小类里。
- 加密密钥换了，存量配置全部解不开 —— 启动时做一次自检：若解密失败，
  记 error 日志并提示「请重新填写模型密钥」，不要让应用直接崩。

### 8.2 其他

1. **只允许一条启用配置**：当前允许多条同时 `status=1`，前端下拉会列出全部。
   是否要保证全局只有一个启用？建议不做（用户可以手动切换用哪条）。
2. **摘要不做缓存**：同一篇文章连点两次会调两次模型（花钱）。
   是否按 `(title, content_hash)` 缓存 10 分钟？建议后续迭代。
3. **超时上限 15 秒（测试）/ 30 秒（生成）**：长文章可能不够。
   是否调大？建议先观察，`max_tokens` 2048 通常 10 秒内能返回。
4. **删除配置不影响历史摘要**：摘要已存在 `articles.summary` 字段里，是普通文本，不依赖模型。
