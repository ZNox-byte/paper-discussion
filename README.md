# AI Infra Systems 论文研究调度器

从 arXiv 检索论文，用可替换的 Flash 模型筛选和并行阅读 32 篇论文，保存原文、证据与模型来源，再交给一个上层审阅者分类、综合和终审。

默认使用 DeepSeek Flash 阅读，由当前会话中的 Codex 审阅。筛选、阅读和备用模型必须配置为 `tier = "flash"`；API 上层必须配置为 `tier = "pro"`。档位由配置明确声明，不根据模型名称猜测，也不会自动把下层失败任务升级给 Pro。

## 工作流

```text
arXiv 检索 / 去重
  → Flash 筛选（保留待定项及未入选候选）
  → Flash 并行阅读（可选另一个 Flash 备用）
  → 本地结构、ID、引文和页码校验
  → 原文存档 + 证据审查包
      ├─ external：交给 Codex 或其他外部审阅者综合、终审
      └─ api：同一个配置的 Pro 模型分阶段综合、终审
                  ↓ 提出具体问题
             Flash 定向补读 → 上层再审
  → 明确批准 + 覆盖与哈希校验 → 最终报告
```

`external` 模式不会调用任何 Pro API，也不要求先存在 Pro 草稿。`api` 模式由 `routing.reviewer` 指定的同一个模型完成分类、技术关系、分章综合和终审。引文在原文中存在，并不自动证明模型的结论成立，事实级核验仍由审阅者负责。

## 安装与检查

需要 Python 3.11+ 和 uv。在项目目录执行以下 PowerShell 命令，将环境、缓存和临时文件全部保存在项目内：

```powershell
$projectRoot = (Get-Location).Path
$env:UV_CACHE_DIR = Join-Path $projectRoot '.uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $projectRoot '.venv'
$env:TEMP = Join-Path $projectRoot '.tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
uv sync --extra dev --locked
.\.venv\Scripts\deepseek-survey.exe doctor
```

`doctor` 只检查本地配置和活跃路由所需密钥，不发送请求、不输出密钥。CLI 不自动读取 `.env`；`.env.example` 仅列出环境变量示例。未启用的供应商无需设置密钥。

## 本地可视化工作台

第一版前端直接读取本项目的 `runs` 目录，无需安装前端依赖或配置 API Key。在项目目录运行：

```powershell
.\start-viewer.ps1
```

打开 <http://127.0.0.1:8765/>。窗口保持运行，按 `Ctrl+C` 关闭服务。也可使用 `.\.venv\Scripts\deepseek-survey.exe serve --runs runs --port 8765`。

- **研究结果**：默认打开最近有定稿的运行，支持报告版本切换、目录导航、分类分布和发表时间轴。
- **论文库**：搜索与筛选本轮、同主题累计和候选论文；勾选 2–4 篇并排比较。
- **证据侧栏**：点击 `[P01]` 等编号查看阅读卡片、引句、页码和已保存的原文上下文。
- **审阅与问题、运行记录**：查看审阅意见、补读请求、历史记录和已记录用量；导出 Markdown 或审查包。

该版本只读、不调用模型、不改写研究产物，服务仅监听本机。历史记录中的缺失原文、未完成阅读和不完整用量会如实标注。新版批准需通过正文与证据包一致性检查；获批正文导出来自该获批版本，阅读卡片可另行导出。界面设计范围见 [前端产品报告](docs/frontend-product-report-v0.1.md)。

## 配置模型

主配置是 [config.toml](config.toml)。`providers` 定义接口和密钥环境变量；`models` 定义模型；`routing` 将角色映射到模型别名，别名不必与实际模型 ID 相同。

默认配置中的关键部分：

```toml
[routing]
screening = "ds_flash"
reader = "ds_flash"
reviewer = "ds_pro"

[review]
mode = "external"
name = "Codex"
max_rounds = 2
```

默认文件已定义 `ds_flash` 和 `ds_pro`，但 external 模式不会调用后者。更换外部审阅者可修改 `review.name`，再交接同一种审查包。使用 Pro API 时，将 `review.mode` 改成 `"api"`，将 `review.name` 改成实际审阅者名称，并让 `routing.reviewer` 指向所选 Pro 模型别名。

支持的接口协议：

| protocol | base_url 示例 | 接口 |
|---|---|---|
| `deepseek` | `https://api.deepseek.com` | Chat Completions，DeepSeek thinking 参数 |
| `openai_compatible` | 供应商文档中的 API 根路径，通常含 `/v1` | Chat Completions，需兼容 JSON 输出 |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta` | 原生 generateContent |
| `anthropic` | `https://api.anthropic.com/v1` | 原生 Messages |

添加另一个厂商的 Flash，可在配置文件追加：

```toml
[providers.other]
protocol = "gemini"
base_url = "https://generativelanguage.googleapis.com/v1beta"
api_key_env = "GEMINI_API_KEY"
max_concurrency = 4
requests_per_minute = 30

[models.other_flash]
provider = "other"
model = "替换为你的账户支持的具体Flash模型ID"
tier = "flash"
max_output_tokens = 12000
```

然后在**现有** `[routing]` 表中把 `reader` 改成 `"other_flash"`，或加上 `reader_fallback = "other_flash"`；不要重复定义 `[routing]`。配置备用后也需要提供它的密钥。主力模型的请求或证据修复耗尽后，备用 Flash 做一次逻辑阅读尝试，底层网络重试仍受供应商上限约束。

推理参数随厂商和代际变化。`thinking` 的统一开关只直接用于 DeepSeek；其他协议默认采用供应商行为，需要显式的 `request_options` 才能改变。例如支持该参数的兼容接口可使用 `[models.your_alias.request_options] reasoning_effort = "low"`。原生 Gemini 可在 `request_options.generationConfig.thinkingConfig` 中设置该具体模型支持的值。配置不能覆盖模型、输入、认证、输出格式或输出上限，每次调用会记录参数控制方式。

模型 ID、功能和账户额度以官方文档为准：[DeepSeek](https://api-docs.deepseek.com/api/create-chat-completion/)、[Gemini](https://ai.google.dev/api/generate-content)、[Anthropic](https://platform.claude.com/docs/en/api/messages/create)。兼容协议并不意味着各家支持相同参数。

## 运行与续跑

```powershell
# 只检索，无需模型密钥
.\.venv\Scripts\deepseek-survey.exe discover

# 默认 Flash 阅读，完成后等待外部审阅
$env:DEEPSEEK_API_KEY = "你的 Key"
.\.venv\Scripts\deepseek-survey.exe run

# 复用候选，或从同一轮继续
.\.venv\Scripts\deepseek-survey.exe run --candidates runs\某轮\candidates.json
.\.venv\Scripts\deepseek-survey.exe run --resume runs\某轮

# 严格匹配阅读模型配置；变更模型的卡片重新阅读
.\.venv\Scripts\deepseek-survey.exe run --resume runs\某轮 --resume-policy strict

# 下一轮排除父轮次链中的历史入选论文
.\.venv\Scripts\deepseek-survey.exe run --next-round-from runs\上一轮
```

`reuse` 是默认策略：输入和证据校验一致时复用卡片，保留原生产模型信息，不会将旧模型结果标成新模型生成。`strict` 还要求阅读主力/备用模型及输出上限等参数相同，否则重新阅读。两种策略均检查原文、提示词和结果指纹；旧版无来源记录的卡片在 reuse 下标为 `legacy_unknown`，strict 下重新阅读。

严格模式更换筛选模型时必须新建运行，以免复用旧模型筛出的集合；研究问题或分类体系改变也需要新建运行。对照评测建议使用相同候选集和新目录，不用 reuse 结果衡量新模型。综合缓存绑定卡片、论文元数据、提示词和上层模型配置。

已完成、配置和原文未变化的运行再次续跑时，会核验现有批准记录并保留完成状态，不重复调用模型。

## 审阅、补读与定稿

external 模式完成后，从 `review_bundle.json` 和 `review/instructions.md` 开始审阅。审查包包含原文上下文、待定候选、失败任务、来源限制、模型记录和检查清单。完整提取文本位于 `sources/Pxx.json`；PDF 提取失败时明确标为仅摘要。长论文普通阅读可使用采样文本，完整提取文本仍存档。

审阅者写出：

- `review/main.md`：分类与跨论文综合正文，每篇使用单独的 `[P01]` 格式引用。
- `review/review.md`：实际核验依据、问题与修订决定。
- `review/decision.json`：参考模板，填写实际 reviewer、决定、唯一主分类、已审任务、未解决问题、覆盖缺口和补读请求。

决定为 `approved`、`needs_revision` 或 `insufficient_evidence`。需要补读时填写 `reread_requests`（`task_id`、`question`、`reason`），运行：

```powershell
.\.venv\Scripts\deepseek-survey.exe reread --run runs\某轮
```

程序按问题重新调用 Flash，使用保存的完整提取文本；超出配置的模型输入上限会明确失败，不静默截掉原文。其他已验证卡片继续复用。API 模式自动进行有上限的“审阅→补读→再审”，超过 `review.max_rounds` 后保留待修订状态。补读后的审查包包含上次问题，旧批准自动失效。

实际审查完成后，以下命令显示正文与证据包 SHA256；把输出填入决定中的对应字段，再定稿：

```powershell
.\.venv\Scripts\deepseek-survey.exe review-hashes --run runs\某轮
.\.venv\Scripts\deepseek-survey.exe finalize-review --run runs\某轮
```

显示哈希不会批准报告。定稿须同时满足明确批准、没有未解决问题或补读请求、所有有效论文被审阅且唯一归类、正文引用完整、正文/证据包未改变。默认至少 28/32 篇通过阅读校验才进入审查；不足 32 篇时，正文和 `coverage_gaps` 都必须披露缺口。最终卡片附录从批准绑定的审查包重建。

API 审查也经过以上检查，并记录实际 API 模型身份。程序不会将拒绝或证据不足自动改成批准；结构与覆盖检查不能替代事实核验。

## 预算与产物

`execution.reader_concurrency` 控制阅读并发，每个 provider 另行控制并发、可选 RPM、重试和超时。`execution.max_requests` 与 `max_total_tokens` 限制当前运行请求与 token 消耗，包含失败请求，续跑继承已消耗预算；它们不是人民币或美元费用上限。

发送前用请求的 UTF-8 字节数加输出上限作保守预留，收到用量后结算。缺少用量的失败请求保留保守估算，明确标为未知实际用量，不当作免费。可选 `max_input_tokens` 使用同样保守的估算检查输入，不代表精确分词。货币成本仍需供应商账单与当时价格核对。

| 文件 | 内容 |
|---|---|
| `run.json`、`round_context.json`、`corpus.json` | 状态、配置历史、轮次与累计论文 |
| `screening/selection.json`、`screening/triage.json` | 入选、待定与未入选候选 |
| `sources/Pxx.json`、`sources/manifest.json` | 完整/实际提供的文本、来源限制和校验值 |
| `results/Pxx.json`、`provenance/Pxx.json` | 卡片、真实模型与输入/结果指纹 |
| `raw/`、`validation/`、`failures.json` | 每次输出、校验和失败记录 |
| `api_usage.json`、`api_attempts.json`、`budget.json` | 成功结果用量、全部请求尝试、预算状态 |
| `upper/<指纹>/synthesis/` | API 上层分阶段综合缓存 |
| `report_cards.md`、`review_bundle.json` | 可读卡片和通用审查包 |
| `report_draft.md` | API 上层草稿，仅 api 模式生成 |
| `review/` | 审查指令、记录、补读焦点与决定 |
| `classification.json`、`report_final.md` | 批准后的分类与最终报告 |

原有 `[deepseek]` 配置和旧版 Codex 定稿文件仍可读取；新运行采用通用审查协议。既有 `runs/` 历史产物不会被主动迁移或改写。

## 测试

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m pytest -q --basetemp=.tmp/pytest
.\.venv\Scripts\ruff.exe check . --no-cache
```

测试使用本地模拟响应，覆盖供应商报文、Flash 约束、重试与预算、并发、备用模型、缓存、外部/API 审查和批准门槛，不发送付费请求。实际账户是否支持所填模型，需要在配置密钥后验证。
