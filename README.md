# Evolutionary Multi-Agent Collaboration System

一个使用 HKGAI / DeepSeek 的可恢复多智能体协作平台。命令行界面为英文，支持群聊、一对一私聊、动态任务委派、独立审核、人工确认、每个智能体独立的文件工作区及持久化记忆。

## 快速开始

本机已经创建项目专用 `.venv` 并配置本地 `.env`。从项目目录运行：

```bash
./run.sh doctor
./run.sh init my-team --scenario software
./run.sh chat my-team
```

进入聊天后可直接输入任务，或使用：

```text
/task Build a meeting-room booking system. Ask me about unclear requirements.
/dm lead What technical approach would you suggest?
/status
/quit
```

私聊是独立的咨询通道，不自动执行工具，也不自动广播给群组。希望团队执行某项工作时，请在群聊中发布任务。

在其他机器安装：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
# 在 .env 中填写自己的 HKGAI_API_KEY
./run.sh doctor --live
```

支持 Python 3.11+、macOS 或 Linux。当前 macOS 可用 Seatbelt 执行沙箱；Linux 需要本地 Docker。安装 Docker 后可准备镜像并在 `.env` 选择 `EVO_SANDBOX=docker`：

```bash
docker pull python:3.12-slim
```

`doctor --live` 会实际调用模型；普通 `doctor`、`init`、`status`、`sessions` 和 `scenarios` 不调用模型。全部自动化测试也不需要密钥。

## API 配置

```dotenv
HKGAI_API_KEY=your-own-key
HKGAI_BASE_URL=https://api1.hkgai.net
HKGAI_MODEL=t2_hkgai-v3_fp8_1m_e7
EVO_SANDBOX=auto
EVO_MAX_STEPS=40
EVO_REQUEST_TIMEOUT=90
EVO_MAX_OUTPUT_TOKENS=4096
```

接口路径为 `/v1/chat/completions`，直接使用 HTTPX，不依赖 OpenAI/Anthropic SDK，也不会访问这些服务。`HKGAI_BASE_URL` 已以课程要求限制为 HKGAI 或 DeepSeek 的 HTTPS 地址。DeepSeek 可设置 `https://api.deepseek.com` 和相应模型名。

密钥只保存在本地忽略文件 `.env`，不会进入会话配置、智能体工作区或源码。新机器请根据 `.env.example` 自行配置，勿上传 `.env`。可选 `EVO_GITHUB_TOKEN` 仅用于经批准的 GitHub 推送。

## 课程的三个场景

已经包含软件团队、新闻编辑部、基金团队各四个角色，以及提供的六份原始英文任务。两个任务必须在同一个 session 中依次运行，才能保留协作上下文、文件和记忆。

```bash
./run.sh init software-demo --scenario software
./run.sh run software-demo --task-file scenarios/software_task1.md --interactive
# 第一项完成后：
./run.sh run software-demo --task-file scenarios/software_task2.md --interactive
```

新闻场景将 `software` 换为 `newsroom`，基金场景换为 `fund`。各任务对应 `scenarios/<scenario>_task1.md` 与 `task2.md`。用 `./run.sh scenarios software` 查看角色和内置任务概述。

课程总说明要求文档使用 `.md` / `.txt`，但基金场景第二项明确要求 HTML 幻灯片。这里保留原始题目，工具允许 HTML 作为代码文件；正式评测时应由需求方确认这项格式冲突。平台不提供 PDF、DOCX、PPT 的解析或生成工具。

也可以用 `--agents agents.json` 自定义团队，JSON 为包含 `id`、`name`、`role` 字符串的数组。第一位成员担任协调者；角色、工具职责可以不同，底层模型仍统一为配置的 HKGAI / DeepSeek。

## 暂停、审批与恢复

无 `--interactive` 时，遇到问题或关键操作，命令保存状态并以退出码 2 返回。随后可用：

```bash
./run.sh status my-team
./run.sh respond my-team "We have three rooms; bookings are in 30-minute slots."
./run.sh respond my-team --approve
./run.sh respond my-team --deny "Please revise the script first."
./run.sh run my-team --steps 20
```

执行 Python、删除文件、Git 提交和推送需要针对具体操作的人工批准。审批请求包含工具参数、工作区指纹和操作摘要；文件变动会使旧批准失效。系统不会根据普通文本中的“yes”自动授权，也不会在批量评测中批准关键操作。

超出回合预算后可用 `run --steps N` 追加预算。Ctrl+C 后状态保留；若工具执行中途被打断，重启会要求核对实际结果，不自动重放可能已经完成的操作。

聊天命令还包括 `/run 20`、`/answer TEXT`、`/approve`、`/deny`。命令行中的每次状态变化都会输出成员与动作；群组消息同步显示。

## 工具与隔离

| 能力 | 实现 |
|---|---|
| 文件 | `read_file`、`write_file`、`list_files`、`delete_file`；拒绝越界路径、符号链接和硬链接 |
| 代码执行 | `run_python`；由 macOS Seatbelt 或 Docker 强制隔离，禁止不受保护的宿主执行回退 |
| 搜索与获取 | `search_web` 使用 Bing RSS；`fetch_url` 获取公开文本网页，保留 URL 和获取时间 |
| 跨成员交接 | `send_file` 显式复制至对方 `inbox/<sender>/<destination>`，记录 SHA-256，不覆盖已有文件 |
| 版本控制 | `git_init`、`git_status`、`git_diff`、`git_commit`、`git_push`；禁用仓库钩子和不可信全局配置 |

每个成员只能访问自己的工作区。成员间消息可以协商与交接；工具结果只注入执行该工具的成员上下文，文件需要显式共享。私聊记录及私聊记忆不注入群聊。

代码沙箱默认提供 Python 标准库及当前工作区代码，禁止联网，不自动安装第三方包。macOS 禁止创建子进程；Docker 可在资源限制内创建子进程。默认执行上限 30 秒，可申请至 120 秒；每个输出流最多保留 64 KiB。

macOS 施加 CPU、文件大小、文件描述符和时间限制，但没有硬性的常驻内存上限或工作区总磁盘配额。Docker 增加 512 MiB 内存、32 进程、1 CPU 限制，并仅挂载当前工作区；挂载目录仍没有总磁盘配额。Docker 要使用本地 daemon，远程 context 不适用本地路径挂载。

联网工具只允许公开 80/443 端口上的文本/HTML/JSON/XML，单次至多 512 KiB，不处理压缩响应。DNS 解析结果和重定向目标均检查并固定连接 IP。网页、文件及模型输出均视为不可信数据；模型不能通过文字指令扩大工具权限。

## 记忆与演进

每个成员有独立 JSONL 记忆：任务经历、审核结果、成功/失败记录与复盘经验。下一项任务按词项及中文二元字组合的相似度检索相关记忆，并加入提示上下文。

完成任务后，各成员根据已记录的实际结果进行一次有界复盘。复盘接口失败时保留事实型回退记录，不破坏已完成结果。这里的“演进”是记忆驱动的提示改进，不是训练或微调模型，也不保证每轮性能必然提升。

## 测试与评测

```bash
.venv/bin/python -m pytest
./run.sh evaluate scenarios/evaluation_smoke.json --output .evoagents/evaluations/my-smoke
```

小型评测包含两项连续任务：文件生成/交接/独立审核，以及同一个团队复用之前产物完成后续任务。`evaluate` 会产生 `results.json`、`report.md` 和完整会话目录，记录总耗时、活跃执行时间、工具调用、致命错误、审核结果及记忆变化。

同伴审核通过和独立验收通过分别计数。测试集支持 `file_exists`、`text_equals`、`text_contains` 三种确定性验收。没有独立规则的开放任务标记为需要人工评审，不能仅凭 AI 的“已完成”当作已验证成功。

原始课程六项任务的批量清单位于 `scenarios/course_mid_test.json`。这些开放任务会触发真实问题和审批，建议使用前述逐项交互方式；批量模式遇到人工请求会保留等待状态，同一团队的后续案例标记为受阻。最终保密测试集尚未提供，项目中的小型验证不代表期末得分。

完整评测口径与格式见 [docs/evaluation.md](docs/evaluation.md)，架构见 [docs/architecture.md](docs/architecture.md)。

## 保存位置与团队开发

```text
.evoagents/sessions/<name>/
  state.json                 当前状态、任务板、指标
  events.jsonl               群组执行审计
  private/<agent>.jsonl       独立私聊记录
  memories/<agent>/          群组与私聊记忆
  agents/<agent>/workspace/  独立工作区、产物、inbox
  runs/<task-id>.json         之前任务的状态快照
```

`.evoagents/` 默认不入 Git，因为它包含任务数据和私聊。分享评测时应选择适当的日志和产物。源码、测试和说明文档可以提交到你们团队仓库。

课程要求真实、持续、每位组员都有贡献的 Git 历史。这份代码没有伪造组员提交；后续应由组员实际分工、修改、测试并各自提交。架构、测试与演进效果需要结合你们真实运行的数据继续完善。展示建议见 [docs/demo.md](docs/demo.md)。
