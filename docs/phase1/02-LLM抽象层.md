# 02 · LLM 抽象层（WP2）

> 工作包：统一 LLM 接口，屏蔽供应商差异，支持多模型切换、自动降级、流式输出，并内置 FakeLLM 供测试。
> 依赖：WP1（配置、日志）。
> 上游：[Phase 1 总览](./README.md) · [01 工程骨架](./01-工程骨架与配置.md)

## 1. 目标

- 对内核（WP3）暴露**一个**稳定接口：`chat` / `stream`，参数带 `tools`。
- 屏蔽 OpenAI / Anthropic / Gemini / OpenRouter 的 SDK 与工具调用格式差异。
- 支持：默认模型、`/model` 手动切换、主模型故障**自动降级**。
- 流式输出统一为事件流（文本增量 / 工具调用增量 / 结束 / 错误）。
- 内置 `FakeLLM`：可脚本化"思考→调工具→回答"，让 e2e 不花真钱、可复现（对应验收 A11/A12、坑 K11）。

## 2. 关键决策

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| L2-1 | 网关 | `litellm` 做底层调用 | 一家库覆盖多家，工具调用格式归一 |
| L2-2 | 路由/降级 | **自研**（不用 litellm Router） | 降级链、审计、用户提示要在自己手里 |
| L2-3 | 工具调用 | 统一转成 **OpenAI function-calling 格式**传给 litellm | 格式最简单、litellm 支持最好 |
| L2-4 | 流式 | litellm `stream=True` + 自研事件归一 | 统一事件模型，内核不感知供应商 |
| L2-5 | 测试 | FakeLLM 实现同一接口 | e2e 确定性、零成本（K11） |

## 3. 接口设计

```python
class LLMProvider(Protocol):
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        model: str | None = None,        # None = 用当前默认模型
        max_tokens: int = 8000,
    ) -> LLMResponse: ...

    def stream(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        model: str | None = None,
        max_tokens: int = 8000,
    ) -> AsyncIterator[StreamEvent]: ...
```

**数据结构**：

```python
@dataclass
class Message:
    role: Literal["system","user","assistant","tool"]
    content: str | None
    tool_calls: list[ToolCall] | None = None     # assistant 发起
    tool_call_id: str | None = None              # tool 结果回填
    name: str | None = None

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict        # 解析后的 JSON，不是字符串

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall]
    model: str
    usage: Usage           # prompt/completion/total tokens

# 流式事件
StreamEvent = TextDelta(text) | ToolCallDelta(id,name,args_fragment) | Done(LLMResponse) | Error(LLMError)
```

> **契约**：`ToolCall.arguments` 在交给内核前**必须是已解析的 dict**。流式中的 JSON 碎片由本层拼接解析（见坑 L2-K2）。

## 4. 模型与路由配置

`config.yaml`：

```yaml
llm:
  default_model: gpt-4o
  fallback_chain: [gpt-4o, claude-3-5-sonnet, gemini-1.5-pro]
  per_model:
    gpt-4o:            { max_tokens: 8000,  context: 128000 }
    claude-3-5-sonnet: { max_tokens: 8000,  context: 200000 }
    gemini-1.5-pro:    { max_tokens: 8000,  context: 128000 }
  timeouts: { connect: 10, read: 120 }
  max_retries: 2
```

**模型能力表**（用于 `/model` 展示 + 校验）：

| 模型 | 供应商 | 工具调用 | 流式 | 备注 |
|------|--------|----------|------|------|
| gpt-4o | OpenAI | ✅ | ✅ | 默认主力 |
| claude-3-5-sonnet | Anthropic | ✅ | ✅ | 长上下文/代码 |
| gemini-1.5-pro | Google | ✅ | ✅ | 多模态备用 |
| openrouter 任意 | OpenRouter | 视模型 | 视模型 | 兜底通道 |

> Phase 1 **不做**按任务类型自动选模型（总览 D2）。路由 = `default_model` + 手动切换 + 故障降级。

## 5. 降级与重试策略

**重试（同一模型内）**：
- 仅对**可重试错误**：网络超时、HTTP 429、5xx。指数退避 `1s → 2s`，最多 `max_retries`。
- **不重试**：400/401/403/404（配置或鉴权问题，重试无意义，直接降级或报错）。

**降级（跨模型）**：
- 触发：某模型重试耗尽 / 401/403（key 无效）/ 连续 2 次工具参数解析失败。
- 动作：沿 `fallback_chain` 顺延下一个**可用**模型（有 key 且支持工具调用）。
- 用户可见：流里插入一条系统事件 `⚠ 主模型不可用，已切换到 <model>`。
- 记录：审计日志记 `model_fallback` 事件（from→to，reason）。
- **不回弹**：本次会话内保持在降级后的模型，直到用户 `/model` 手动切回。

**"可用"判定**：`has_key(provider) and supports_tools(model)`。启动 `lh --check` 时预检并提示。

## 6. FakeLLM 设计（测试基石）

```python
class FakeLLM(LLMProvider):
    """按剧本回放。剧本 = list[Step]，Step 决定这一轮返回文本还是工具调用。"""
    def __init__(self, script: list[FakeStep]): ...
```

- `FakeStep(text=...)` → 返回纯文本（视为最终回答，结束循环）。
- `FakeStep(tool="file_write", args={...})` → 返回工具调用（内核执行后把结果喂回，继续剧本）。
- 支持 `stream`：把 `text` 切成若干 `TextDelta` 模拟流式。
- 支持"故障注入"：`FakeStep(error=LLMError(500))`，用于测降级（A12）。
- 记录所有被调用参数 → 测试断言用。

> FakeLLM 让 **A2/A8/A9/A12** 全部可离线验证（K11 的直接解法）。

## 7. 上下文与 token 预算

- 每轮 `max_tokens` 来自配置；`prompt + completion` 计入 `Usage`。
- 本层只做**传递与记录**，真正的上下文裁剪在 WP3（内核）做，避免职责重叠。
- 本层负责：调用前用 `per_model.context` 做一次**粗校验**（估算 prompt 是否超窗），超了抛 `ContextTooLarge` 让内核裁剪，而不是把 400 错误漏给用户。

## 8. 密钥与安全

- key 只从 `.env`/环境读，注入 litellm `api_key` 参数，**不进日志、不进审计、不进异常消息**。
- 异常消息里的 URL/header 先过脱敏过滤器再抛出（联动 WP6）。
- 支持 `base_url` 覆盖（代理/自建网关），但 `base_url` 非标准域名时给出提示。

## 9. 边界

- 本层**不**决定"该不该调工具"（那是内核），只负责"把调用可靠地送达并解析回来"。
- 本层**不**做工具执行。
- 多模态（图片输入）Phase 1 不启用，接口预留 `content` 可扩展。

## 10. 本包的坑

| # | 坑 | 现象 | 对策 |
|---|-----|------|------|
| K1 | 各家 tool-call/流式格式不同 | 参数解析失败、流式乱码 | litellm 归一 + 统一转 OpenAI 格式；`ToolCall.arguments` 强制解析成 dict 才出层 |
| L2-K2 | 流式中 tool 参数是 JSON 碎片 | 提前解析报 JSONDecodeError | 本层累积 `args_fragment` 到 `Done` 再整体 `json.loads`；解析失败走"回喂重试"（见下） |
| L2-K3 | 不同模型 max_tokens 语义不同（含/不含 prompt） | 输出被截断或 400 | `per_model.max_tokens` 各自配；截断时检测 `finish_reason=length` 并提示 |
| L2-K4 | 某模型工具调用返回空/畸形 | 内核拿到空 tool_calls | 解析失败计入"连续失败"，达 2 次触发降级；同时回喂一条"参数不合法"让模型自纠 1 次 |
| L2-K5 | 401/403 被当成可重试 | 无谓等待 | 明确 4xx（除 429）不可重试，直接降级/报错 |
| L2-K6 | litellm 版本升级行为变化 | 工具调用悄悄不工作 | 锁版本；每次升级跑"每家 1 次带工具+流式"冒烟（`-m llm`） |
| L2-K7 | 代理/公司网络 | 连接超时 | 支持 `http_proxy`/`base_url`；`timeouts` 可配 |
| L2-K8 | key 出现在异常栈 | 泄密 | 异常脱敏过滤器（WP6）；litellm 自定义 error mapper |
| L2-K9 | 估算 token 不准 | 误判超窗/漏判 | 粗校验只拦"明显超"（> 0.9×context），边界情况交给真实 400 → 触发内核裁剪 |

## 11. 验收（本包 DoD）

- [ ] FakeLLM 下：纯文本回答、单工具调用、多轮"调用→结果→回答"全通过（单测）。
- [ ] FakeLLM 故障注入：500 → 自动切到链上下一模型，产生 `model_fallback` 审计（A12）。
- [ ] 至少 1 家真实供应商：带工具 + 流式冒烟通过（`pytest -m llm`，手动/CI 可选）。
- [ ] `/model` 切换后，后续调用使用新模型（单测断言 `model` 参数）。
- [ ] 400/401 不重试、429/5xx 重试、重试耗尽降级（单测 mock）。
- [ ] 日志/异常/审计中 grep 不到任何 key（联动 A6）。
- [ ] `ContextTooLarge` 在超窗粗校验时正确抛出。
- [ ] 核心模块单测覆盖 ≥ 80%（A13 的一部分）。

## 12. 交付物

`src/yellowbull/llm/{base,gateway,routing,fake}.py`、`config/schema.py` 中 llm 段、`tests/unit/test_llm_*.py`、真实 API 冒烟测试（`-m llm`）、模型能力表文档。
