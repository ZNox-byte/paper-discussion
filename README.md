# AI Infra Systems 论文并行研究项目

这是一个以 vLLM 为代表主题的可审计 AI Infra Systems 论文综述调度器：从 arXiv 检索真实
系统论文，让 DeepSeek API 从候选池筛选 32 篇，并行执行 32 个阅读任务，逐份校验结构和
原文证据，最后分类并生成一份跨论文综述。

当前项目已经搭建完成，但**不会在没有 `DEEPSEEK_API_KEY` 时调用 DeepSeek API**。论文检索可
单独运行，不需要 DeepSeek Key。

## 工作流

```text
多查询 arXiv 检索与去重
          │
          ▼
本地相关性预排（最多 128 篇候选）
          │
          ▼
DeepSeek 严格筛选 32 篇并生成逐篇阅读焦点
          │
          ▼
并发下载/提取 PDF ──失败时明确降级为摘要
          │
          ▼
同时调度 P01…P32 共 32 个 DeepSeek 阅读任务
          │
          ▼
JSON Schema + ID + 分类白名单 + 原文逐字证据/页码校验
          │  不通过：任务内最多修复两次
          ▼
分类索引 + DeepSeek 跨论文综合 + 引用覆盖校验
          │
          ▼
report.md 与全套中间审计产物
```

arXiv 负责可追溯的论文发现和原文获取；DeepSeek 负责语义筛选、阅读和综合。API 模型不会被
假定具有联网搜索能力，也不会允许凭记忆补齐未提供的论文内容。

## 安装

需要 Python 3.11+。推荐使用 [uv](https://docs.astral.sh/uv/)：

```powershell
uv sync --extra dev
uv run deepseek-survey doctor
```

也可以使用普通虚拟环境：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
deepseek-survey doctor
```

`doctor` 只检查本地状态，不会发送网络请求。未设置 Key 时会正常显示：

```text
DEEPSEEK_API_KEY: 未设置（当前可先运行 discover）
```

## 使用

### 1. 可选：先只做论文检索

```powershell
uv run deepseek-survey discover
```

命令会在 `runs/<UTC时间>/candidates.json` 保存去重后的候选元数据，不调用 DeepSeek。

### 2. 设置 Key 后运行完整项目

仅对当前 PowerShell 会话设置：

```powershell
$env:DEEPSEEK_API_KEY = "你的 Key"
uv run deepseek-survey run
```

若已运行过 `discover`，可复用候选文件：

```powershell
uv run deepseek-survey run --candidates runs\<时间>\candidates.json
```

中断或部分任务失败后可从同一目录续跑；已经通过证据校验的结果不会重调：

```powershell
uv run deepseek-survey run --resume runs\<运行时间>
```

### 3. 逐轮扩充且不重复论文

第一轮结束后，以上一轮目录启动下一轮：

```powershell
uv run deepseek-survey run --next-round-from runs\<上一轮时间>
```

新一轮默认复用上一轮的 `candidates.json`，沿父轮次链排除所有历史入选论文，再用 Flash
筛选 32 篇新论文、Flash 并发阅读，最后交给 Pro 分类汇总。排除同时比较 arXiv ID、DOI 和
规范化标题，因此论文版本或标识变化也不会轻易造成重复。

第三轮应从第二轮目录启动，而不是再次从第一轮启动：

```powershell
uv run deepseek-survey run --next-round-from runs\<第二轮时间>
```

如果原候选池剩余不足 32 篇，可先扩展 `config.toml` 中的查询，再检索新候选，并同时指定：

```powershell
uv run deepseek-survey run `
  --next-round-from runs\<上一轮时间> `
  --candidates runs\<新检索时间>\candidates.json
```

`--resume` 表示继续同一轮；`--next-round-from` 表示创建不重复的新一轮，两者不能同时使用。

CLI 不读取 `.env` 文件，Key 只从环境变量 `DEEPSEEK_API_KEY` 获取，也不会写入任何运行产物。

## 配置

主配置为 [`config.toml`](config.toml)。默认设置包括：

- 固定 32 篇目标论文、32 路阅读并发；
- 官方 OpenAI 兼容 Base URL `https://api.deepseek.com`；
- 候选筛选和 32 篇逐篇阅读使用 `deepseek-v4-flash`；
- 分类与跨论文最终综合使用 `deepseek-v4-pro`，thinking mode 为 `enabled`；
- 14 组围绕 vLLM/PagedAttention、SGLang、KV Cache、请求调度、prefill/decode 解耦、
  speculative decoding、FlashAttention、模型并行和训练系统的 arXiv 查询；
- PDF 最多向单任务提供 180,000 字符，超长论文保留头部、中部和结尾采样；
- 每篇最终至少保留两条可逐字回查的证据；无效的额外证据会被剔除，证据不足时最多修复两次。
- PDF 提取文本和 API JSON 在发送前会清洗非法 Unicode 代理字符。
- 计划 32 篇；至少 28 篇通过验证即可生成带缺口说明的 Pro 部分汇总。

可以调整查询、分类体系、超时和 token 上限。`project.target_papers` 固定为 32；如需降低实际并发
以适应账户或网络条件，可把 `reader_concurrency` 调低，但保留 32 个总任务。

官方文档说明 JSON Output 需要 `response_format={"type":"json_object"}`，且提示词必须明确要求
JSON；本项目两项都已设置，并额外处理空内容、截断、429/500/503 和网络超时。模型名和价格会
变化，正式运行前建议查看 [DeepSeek Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/)
与 [JSON Output](https://api-docs.deepseek.com/guides/json_mode/) 文档。

## 运行产物

每次完整运行单独写入 `runs/<UTC时间>/`：

```text
run.json                       # 运行状态与配置摘要
round_context.json             # 当前轮次、父轮次与累计排除集合
candidates.json                # 检索到的候选元数据
excluded_candidates.json       # 因历史轮次而排除的候选论文
screening/selection.json       # 32 篇入选结果及阅读焦点
tasks/P01.md ... P32.md        # 32 份可读任务指令
tasks/manifest.json            # 任务映射
content_status.json            # PDF/摘要来源与提取状态
raw/                           # 每次 DeepSeek 阅读原始 JSON
validation/                    # 每次校验报告
results/P01.json ... P32.json  # 通过校验的结构化结果
reader_classification.json     # Flash 阅读结果的初始分类索引
classification.json            # Pro 综合阶段确认的最终分类索引
corpus.json                    # 从第一轮至当前轮的累计唯一论文清单
synthesis/                     # 跨论文综合原始值与校验结果
api_usage.json                 # 请求 ID、模型和 token 用量（不含 Key）
report.md                      # 最终综述
```

32 份阅读结果全部通过时，`run.json` 标记为 `completed`；通过数达到配置阈值（默认 28）但
不足 32 时，仍会由 Pro 汇总已验证论文并标记为 `completed_with_gaps`。低于阈值才停止汇总。

## 测试

```powershell
uv run pytest
uv run ruff check .
```

测试完全离线，不需要 API Key。
