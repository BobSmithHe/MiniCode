# MiniCode — AI 编程智能体框架

**个人项目 | 2025.05 — 至今**

**项目描述：** 从零构建类 Claude Code 的 AI 编程智能体系统，基于 Anthropic SDK，支持 DeepSeek/Claude 等多模型后端。采用模块化架构，完整实现了工具调用、上下文压缩、记忆管理、多智能体协作、沙箱隔离等工程化能力，可作为个人 AI 编程助手的核心引擎。

**技术栈：** Python 3.10+, Anthropic SDK, DeepSeek API, Subprocess, Threading, JSON Lines, YAML Frontmatter

---

## 核心模块设计

### 1. Agent 主循环 (`planner/workflow.py`)
- 设计 `while True` 式 agent loop：接收用户输入 → LLM 推理 → 解析 `tool_use` → 执行工具 → 注入 `tool_result` → 继续循环
- 支持 `stop_reason == "max_tokens"` 自动升级 token 预算并断点续传
- 支持 `compact` 内联指令，agent 可主动触发上下文压缩后继续工作

### 2. 四层上下文压缩管线 (`memory/compactor.py`)
- **L1 tool_result_budget**: 超大工具输出（>30KB）自动持久化到磁盘，消息中仅保留摘要
- **L2 snip_compact**: 消息数 > 50 时，保留头尾 + 中间插入 `[snipped N messages]` 标记
- **L3 micro_compact**: 仅保留最近 3 个完整工具结果，旧结果替换为占位符
- **L4 compact_history**: 调用 LLM 生成对话摘要，将整个历史替换为单条压缩消息
- 在 LLM 返回 `context_length_exceeded` 时自动触发 `reactive_compact` 降级恢复

### 3. 持久化记忆系统 (`memory/writer.py`)
- 实现 YAML Frontmatter 格式的 `.memory/*.md` 文件存储，支持 user / feedback / project / reference 四种记忆类型
- **记忆选择**: 基于 LLM 的相关性筛选 + 关键词匹配 fallback，每轮对话自动注入相关记忆到用户消息
- **记忆提取**: 每轮对话结束后调用 LLM 从原始对话中提取新记忆，去重后持久化
- **记忆合并**: 记忆文件 ≥ 10 条时触发 LLM 合并去重，删除过时/矛盾条目

### 4. 工具注册与分发 (`tools/registry.py`)
- 实现统一工具注册表，支持 28 个内置工具（bash、文件读写、任务管理、cron 调度、MCP、worktree、多智能体通讯）
- 动态工具池组装：内置工具 + MCP 服务器发现工具合并为一个 schema 列表传给 LLM
- `call_tool_handler` 统一分发，参数校验失败自动捕获 TypeError 返回错误信息

### 5. 跨平台权限管线 (`protocols/events.py`)
- 实现 PreToolUse / PostToolUse / Stop / UserPromptSubmit 四类 hook 扩展点
- `permission_hook` 自动拦截危险操作：Linux（`rm -rf /`、`mkfs`）+ Windows（`diskpart`、`reg delete`、`\\.\PhysicalDrive`）
- 破坏性操作交互式确认（`chmod 777`、`icacls`、`shutdown /s`），路径逃逸检测（跨平台）

### 6. 任务系统与依赖图 (`tools/task/__init__.py`, `planner/graph.py`)
- 文件持久化任务记录（JSON），支持 `pending → in_progress → completed` 状态流转
- `blockedBy` 依赖链：自动检测前置任务完成状态，未解除依赖前拒绝认领
- 任务完成时自动扫描并提示被解锁的后置任务

### 7. 后台任务与 Cron 调度 (`executor/executor.py`, `infra/scheduler/__init__.py`)
- 慢操作（`pip install`、`npm install`、`pytest` 等）自动识别并放入 daemon 线程异步执行
- 完成后以 `<task_notification>` 格式注入消息流，主循环无需轮询
- 实现 5 字段 cron 引擎（支持 `*/5`、`1-5`、逗号列表），支持 durable 持久化和会话级调度
- 自动触发调度的 daemon 线程 + cron_autorun_loop，实现定时任务注入

### 8. 多智能体协作 (`protocols/team.py`, `protocols/messaging.py`)
- 基于 JSONL 信箱的 `MessageBus`：智能体间通信以追加式 JSONL 文件实现，可落盘审计
- `spawn_teammate_thread`：每个 teammate 独立 daemon 线程运行，拥有自己的 `messages[]` 上下文
- 实现 shutdown 握手协议和 plan 审批协议，通过 `request_id` 匹配请求-响应，防止错配
- 空闲轮询 + 自动认领：teammate 闲置时自动扫描待认领任务并开始工作

### 9. Git Worktree 沙箱隔离 (`tools/git/__init__.py`)
- 任务与 worktree 绑定：创建 worktree 时关联 task_id，工作目录自动切换
- 安全删除保护：移除前检查 uncommitted 文件数和 unpushed commits，拒绝意外删除
- 事件审计日志（`events.jsonl`）记录所有 create / remove / keep 操作

### 10. MCP 插件系统 (`infra/mcp/__init__.py`)
- 实现 MCP Client 抽象：支持工具注册、发现、调用，mock docs/deploy 两套服务器用于教学
- 工具名规范化（`mcp__{server}__{tool}`），与内置工具统一编入工具池
- 危险 MCP 操作（deploy）触发权限确认

### 11. 错误恢复 (`infra/llm/__init__.py`)
- 429 限流：指数退避重试（500ms 起，上限 32s），最多重试 3 次
- 529 过载：连续 2 次后自动切换到备用模型
- `prompt_too_long`：触发 reactive compact 后重试

---

## 工程实践

- **模块化拆分**：从 2000+ 行单文件重构为 20+ 模块的分层架构，清晰的 `planner/executor/tools/memory/protocols/infra` 分层
- **测试覆盖**：编写 165 项单元/集成测试，覆盖全部 20 个功能模块
- **跨平台兼容**：Windows GBK 编码修复、大小写不敏感权限检测、跨平台危险命令库

---

## 收获与成长

- 深入理解了 LLM Agent 的核心机制：tool-use 循环、上下文管理、memory 持久化
- 掌握了多智能体协作模式：消息总线、协议匹配、计划审批
- 实践了从教学代码到工程化模块的重构过程
- 复现了 Claude Code 的核心工作流程，理解了其设计决策背后的 tradeoff
