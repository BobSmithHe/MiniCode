# MiniCode — AI 编程智能体框架

从零构建的 AI 编程智能体，类 Claude Code 架构。基于 Anthropic SDK，支持多模型后端。

```
..\MiniCode\
  .env                          # API 配置 (ANTHROPIC_BASE_URL / MODEL_ID)
  run.py                        # 入口: python run.py
  Agent\
    main.py                     # CLI 交互主循环
    planner\
      workflow.py               # Agent 主循环 (tool_use 解析/执行)
    tools\
      registry.py               # 工具注册表 + handler 分发
      shell\                    # bash 执行
      file\                     # read / write / edit / glob
      task\                     # 任务系统 (CRUD + 依赖图)
      git\                      # Worktree 沙箱
    memory\
      writer.py                 # 记忆写入 / 提取 / 合并
      long_term.py              # 上下文注入
      short_term.py             # System Prompt 组装 + 技能加载
      compactor.py              # 四层上下文压缩
    executor\
      executor.py               # 后台任务线程
      subagent.py               # 子代理 (上下文隔离)
    protocols\
      events.py                 # Hook 管线 + 跨平台权限
      messaging.py              # MessageBus (JSONL 信箱)
      approval.py               # 关机握手 / plan 审批协议
      team.py                   # 多智能体协作
    infra\
      config\                   # 全局配置 / 常量
      llm\                      # LLM 调用 + 错误恢复
      scheduler\                # Cron 调度器
      mcp\                      # MCP 插件系统
      storage\                  # 安全路径解析
      logging\                  # 线程安全日志
  skills\                       # 技能文件 (SKILL.md)
```

## 快速开始

```bash
# 配置 .env
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=sk-xxx
MODEL_ID=deepseek-v4-flash

# 安装依赖
pip install anthropic python-dotenv

# 启动
python run.py
```

## 核心实现

### Agent 循环与工具系统

**主循环** — `Agent/planner/workflow.py:55-154`

`agent_loop(messages, context)` 是核心 `while True` 循环。每一步：准备上下文 → 调用 LLM → 解析 `response.content` 中的 `tool_use` blocks → 逐个执行工具 → 将 `tool_result` 追加到 `messages` → 继续循环。当 LLM 返回纯文本（不再调用工具）时退出。

**工具注册表** — `Agent/tools/registry.py:174-395`

`BUILTIN_TOOLS` 定义 28 个工具的 JSON Schema。`assemble_tool_pool()` 将内置工具与 MCP 服务器发现的工具合并为统一 schema 列表传给 LLM。`call_tool_handler(handler, args, name)` 统一分发，参数校验失败自动捕获 `TypeError` 返回错误信息，不会中断主循环。

**max_tokens 升级与断点续传** — `Agent/planner/workflow.py:83-95`

当 LLM 返回 `stop_reason == "max_tokens"` 时：首次将 `max_tokens` 从 8000 升级到 16000 重试；再次触发则注入 `CONTINUATION_PROMPT` 让模型从断点继续。最多续传 2 次。

**错误恢复** — `Agent/infra/llm/__init__.py:27-52`

`with_retry(fn, state)` 包装 LLM 调用。429 限流 → 指数退避重试（500ms 起，最大 32s），最多 3 次。529 过载 → 连续 2 次后自动切换到 `FALLBACK_MODEL`。其他异常直接抛出，由 `agent_loop` 的 try/except 捕获并注入 `[Error]` 消息。

**MCP 插件** — `Agent/infra/mcp/__init__.py:18-104`

`MCPClient` 类支持工具注册/发现/调用。`connect_mcp(name)` 连接 mock 服务器（docs / deploy），工具名规范化为 `mcp__{server}__{tool}` 后并入统一工具池。危险 MCP 操作（deploy）触发权限确认。

---

### 上下文压缩与记忆持久化

**四层压缩管线** — `Agent/memory/compactor.py:46-137`

`prepare_context(messages)` 串联四层，由 `agent_loop` 每轮调用：

| 层 | 函数 | 触发条件 | 策略 |
|----|------|---------|------|
| L1 | `tool_result_budget` | 本轮 tool_results 总大小 > 200KB | 超大结果写入 `.task_outputs/tool-results/` 磁盘文件，消息中仅留 `<persisted-output>` 预览（2KB 截断） |
| L2 | `snip_compact` | 消息总数 > 50 | 保留头 3 + 尾 46，中间插入 `[snipped N messages]` |
| L3 | `micro_compact` | 工具结果总数 > 3 | 仅保留最近 3 个完整结果，旧结果替换为 `[Earlier tool result compacted.]` |
| L4 | `compact_history` | 消息整体大小 > 50KB | 保存 JSONL 转录到 `.transcripts/`，调用 LLM 生成摘要，历史替换为单条 `[Compacted]` 消息 |

**reactive compact** — `Agent/memory/compactor.py:119-127` / `Agent/planner/workflow.py:73-77`

当 LLM 返回 `prompt_too_long` 错误时触发。保存转录后调用 LLM 生成摘要，保留最近 5 条消息。LLM 摘要失败时降级为静态占位字符串。

**记忆写入** — `Agent/memory/writer.py:27-37`

`write_memory_file(name, type, description, body)` 将记忆写入 `.memory/{slug}.md`，使用 YAML Frontmatter（name / description / type）+ Markdown body 格式。写完后自动调用 `_rebuild_index()` 重建 `MEMORY.md` 索引。

**记忆提取** — `Agent/memory/writer.py:173-230`

`extract_memories(messages)` 取最近 10 条对话，构造 Prompt 让 LLM 从中提取新记忆（name/type/description/body JSON 数组），与已有记忆对比去重后写入磁盘。

**记忆筛选** — `Agent/memory/writer.py:96-156`

`select_relevant_memories(messages)` 取最近 3 条用户消息，调用 LLM 从 memory 目录中选择相关文件。LLM 失败时降级为关键词匹配（>3 字符的单词命中 name+description）。

**记忆注入** — `Agent/memory/writer.py:159-170` / `Agent/planner/workflow.py:41-52`

`load_memories(messages)` 调用 `select_relevant_memories` 获取相关文件名，读取完整内容包裹在 `<relevant_memories>` 标签中返回。`_build_request()` 将其拼接到当前用户消息内容前面（s09 原版模式：memory 放在 user message 而非 system prompt，以获得更高注意力权重）。

**System Prompt 组装** — `Agent/memory/short_term.py:72-99`

`assemble_system_prompt(context)` 运行时拼接 system prompt，包含 identity、工具列表、工作目录、当前时间、技能目录、memory 索引、MCP 服务器列表。

**技能加载** — `Agent/memory/short_term.py:29-67`

`scan_skills()` 扫描 `skills/` 目录中每个子文件夹的 `SKILL.md`，解析 YAML Frontmatter，注册到 `SKILL_REGISTRY`。`load_skill(name)` 按需返回完整技能内容。

---

### 多智能体协作与安全管控

**MessageBus** — `Agent/protocols/messaging.py:16-35`

`MessageBus` 类实现基于 JSONL 文件信箱的智能体通信。`send(from, to, content)` 追加一行 JSON 到 `.mailboxes/{to}.jsonl`。`read_inbox(agent)` 读取全部消息后删除文件（消费语义）。支持消息类型（message / shutdown_request / plan_approval_response）和 metadata 透传。

**Teammate 生成** — `Agent/protocols/team.py:80-278`

`spawn_teammate_thread(name, role, prompt)` 为每个 teammate 起独立 daemon 线程，拥有自己的 `messages[]` 上下文和工具子集（bash / read / write / send_message / list_tasks / claim_task / complete_task / submit_plan）。支持 worktree 绑定：认领任务时自动切换工作目录。

**协议系统** — `Agent/protocols/approval.py:27-82`

`pending_requests` 字典跟踪所有待决协议请求，通过 `request_id` 匹配请求-响应：

- **shutdown 协议**：lead 发送 `shutdown_request` → teammate 回复 `shutdown_response` → lead 通过 `consume_lead_inbox` 消费并更新状态
- **plan 审批协议**：teammate 提交 plan（`submit_plan` 工具） → lead 收到 `plan_approval_request` → lead 调用 `review_plan(request_id, approve)` → teammate 收到 `plan_approval_response`

**空闲自动认领** — `Agent/protocols/team.py:33-65`

`idle_poll()` 每 5 秒检查收件箱和待认领任务列表。发现未认领任务时自动调用 `claim_task`，将任务推入 teammate 的消息队列。支持超时退出（60 秒无活动）。

**Hook 管线** — `Agent/protocols/events.py:7-27`

Hook 系统提供四个扩展点：`UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop`。`trigger_hooks(event, *args)` 依次调用所有注册的 hook，任一 hook 返回非 None 值则停止并返回该值（用于权限拦截）。

**跨平台权限** — `Agent/protocols/events.py:33-56` + `Agent/infra/config/__init__.py:61-83`

`permission_hook` 作为 `PreToolUse` hook 注册。分三层：

1. **DENY_LIST** — 自动拒绝，无确认机会：`rm -rf /`、`mkfs`、`dd if=`（Linux）；`diskpart`、`format`、`reg delete`、`del /f /s C:\`（Windows）
2. **DESTRUCTIVE** — 警告 + `input()` 交互确认：`rm`、`chmod 777`、`> /etc/`（Linux）；`del`、`rd`、`icacls`、`takeown`、`shutdown /s`（Windows）
3. **路径逃逸** — `safe_path()` 校验路径不超出 WORKDIR；额外硬编码拦截 `/etc/`、`/usr/`、`C:/Windows` 等系统路径

**Git Worktree 沙箱** — `Agent/tools/git/__init__.py:59-114`

`create_worktree(name, task_id)` 创建 `git worktree add` 到 `.worktrees/{name}`，将 task 的 `worktree` 字段绑定。`remove_worktree` 删除前统计 uncommitted 文件和 unpushed commits，有变更时拒绝删除（除非显式传 `discard_changes=true`）。所有操作记录到 `events.jsonl` 审计日志。

**任务依赖图** — `Agent/tools/task/__init__.py:59-66`

`can_start(task_id)` 遍历 `blockedBy` 列表，检查所有前置任务是否存在且状态为 `completed`。`claim_task` 在认领前调用此检查，依赖未满足时拒绝并列出具体阻塞项。

**后台任务** — `Agent/executor/executor.py:18-76`

`should_run_background(tool_name, input)` 通过关键词匹配识别慢操作（`install`/`build`/`test`/`deploy`/`compile` 等）。`start_background_task(block, handlers)` 在 daemon 线程中执行，立即返回占位 tool_result。完成后以 `<task_notification>` 格式注入主循环，无需轮询。

---

## 数据流

```
用户输入 (> )

  v
main.py: agent_loop(history, context)
  │
  ├── load_memories()             # 选取相关记忆，冻结到本轮
  ├── prepare_context()           # L1→L2→L3→L4 四层压缩
  ├── assemble_system_prompt()    # identity + tools + memory 索引
  ├── _build_request()            # 记忆拼到 user message 前面
  ├── call_llm()                  # Anthropic SDK → API
  │     └── with_retry()          # 429/529 恢复
  ├── for each tool_use:
  │     ├── trigger_hooks(PreToolUse)  → permission_hook / log_hook
  │     ├── call_tool_handler()        → handler(**input)
  │     └── trigger_hooks(PostToolUse) → post_tool_log_hook / large_output_hook
  ├── [stop] → trigger_hooks(Stop) → after_turn_memories()
  │              └── extract_memories()   # LLM 提取新记忆
  │              └── consolidate_memories() # ≥10 条合并
  └── print assistant response
```

## 记忆文件格式

```markdown
---
name: user-preference-tabs
description: user prefers tab indentation
type: user
---

Always use tabs for indentation in all Python files.
## Why: the user stated this preference explicitly.
```

`.memory/MEMORY.md` 作为索引文件自动维护，每行一个条目：

```markdown
- [user-preference-tabs](user-preference-tabs.md) — user prefers tab indentation
- [project-api-migration](project-api-migration.md) — API v2 migration in progress
```

## Hook 扩展机制

```python
from Agent.protocols.events import register_hook, HOOKS

# 自定义 hook: 统计工具调用次数
def tool_counter(*args):
    # args[0] = tool_use block (PreToolUse) 或 (block, output) (PostToolUse)
    register_hook("PreToolUse", tool_counter)
```

四个 hook 点注册的函数在 `trigger_hooks` 中按注册顺序依次调用，任一返回非 None 即中断。

## 技能系统

`skills/` 目录下每个子文件夹为一个技能，必须包含 `SKILL.md` 文件：

```markdown
---
name: my-skill
description: my custom skill
---

# My Skill

## Instructions
...
```

Agent 通过 `load_skill(name)` 工具按需加载完整技能内容注入上下文。
