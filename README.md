# 老黄牛（yellowbull）

通用型 AI 工作助手：写代码 / 干活（文件、办公、媒体）/ 找信息。
交互路径：命令行（Phase 1）→ 文本界面 → 语音交互。

- 项目总体规划：[docs/项目总体规划.md](docs/项目总体规划.md)
- Phase 1 开发计划：[docs/phase1/README.md](docs/phase1/README.md)

## 快速上手

```powershell
# 1. 准备 Python >= 3.11 的虚拟环境（本仓库使用 venv/）
# 2. 安装依赖（推荐 uv）
uv pip install --python venv\python.exe ".[dev]"

# 3. 配置密钥
copy .env.example .env
#    编辑 .env，至少填一家 LLM 的 API Key（OpenAI / Anthropic / Google / OpenRouter）

# 4. 环境自检
venv\python.exe -m yellowbull --check

# 5. 启动
venv\python.exe -m yellowbull
# 或安装后直接使用命令：
lh
```

## 开发

```powershell
venv\python.exe -m pytest            # 单测 + e2e 剧本（不花真钱）
venv\python.exe -m pytest -m llm     # 真实 API 冒烟（需 key）
ruff check src tests
```
