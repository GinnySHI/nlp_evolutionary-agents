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

当前课程运行使用 DeepSeek 作为主干模型：

```dotenv
EVO_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-own-deepseek-key
DEEPSEEK_MODEL=deepseek-flash
EVO_SANDBOX=auto
EVO_MAX_STEPS=120
EVO_REQUEST_TIMEOUT=240
EVO_MAX_OUTPUT_TOKENS=16384
EVO_REASONING_EFFORT=low
```

改用 HKGAI 时设置 `EVO_PROVIDER=hkgai`、`HKGAI_API_KEY` 和 `HKGAI_BASE_URL=https://api1.hkgai.net`。两家服务各自需要独立密钥，不能互相复用。`EVO_PROVIDER=deepseek` 时 base URL 固定为 `https://api.deepseek.com`，忽略 `HKGAI_BASE_URL`。DeepSeek 可用模型为 `deepseek-v4-pro` 与 `deepseek-flash`（`deepseek-chat` 为 flash 的别名）。

接口路径为 `/v1/chat/completions`，直接使用 HTTPX，不依赖 OpenAI/Anthropic SDK，也不会访问这些服务。按课程要求，base URL 被限制为 HKGAI 或 DeepSeek 的 HTTPS 地址，配置其他服务会在发出任何请求前报错。

本次课程测试使用 `deepseek-flash`、`EVO_MAX_STEPS=120`、`EVO_MAX_OUTPUT_TOKENS=16384`、`EVO_REQUEST_TIMEOUT=240`、`EVO_REASONING_EFFORT=low`；`.env.example` 与这些设置一致。这些是运行预算，不保证任务通过。推理 token 也占用输出预算；降低推理强度可以减少推理耗尽预算却没有可执行输出的情况。备用服务默认关闭；只有显式设置 `EVO_DEEPSEEK_FALLBACK=true` 且提供独立 DeepSeek 密钥后，HKGAI 网络错误、402 余额不足、429 或指定 5xx 服务错误才会触发切换。402 不自动重试同一服务；认证失败、内容拒绝、截断和格式错误不会触发跨服务重试。`doctor` 会显示备用是否就绪，不输出密钥。

模型请求使用 JSON 输出模式；服务明确不支持该参数时才回退。空内容或响应结构异常最多尝试三次。截断输出不会执行，而是提示成员缩短动作、分块写文件；连续三次截断仍会停止。可获得的 usage 在截断或响应异常时也计入统计，网络超时等未返回 usage 的消耗仍可能缺失。

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

也可以用 `--agents agents.json` 自定义团队。数组中的每个成员包含 `id`、`name`、`role` 字符串，以及可选的 `allowed_tools` 工具名称列表。第一位成员担任协调者。自定义配置省略白名单或设为 `null` 时沿用全量工具，`[]` 表示禁用全部工具。已有会话缺少白名单时也沿用原权限。切换到内置白名单可以创建新的会话。

内置场景按角色分配工具。以 `smoke` 场景为例，编写员能写入并共享文件，审核员只能列出和读取文件。在 `software` 场景中，开发工程师和测试工程师可以申请执行 Python，发布经理负责 Git 操作。编排器根据白名单展示工具，并在接收工具请求及恢复已获批准的操作时检查权限。删除文件、执行 Python、Git 提交和推送仍须人工批准。

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
| 文件 | `read_file`、`write_file`、`append_file`、`replace_text`、`list_files`、`delete_file`；拒绝越界路径、符号链接和硬链接 |
| 代码执行 | `run_python`；由 macOS Seatbelt 或 Docker 强制隔离，禁止不受保护的宿主执行回退 |
| 搜索与获取 | `search_web` 使用 Bing RSS；`fetch_url` 获取公开文本网页，保留 URL 和获取时间 |
| 跨成员交接 | `send_file` 显式复制至对方 `inbox/<sender>/<destination>`，记录 SHA-256，不覆盖已有文件 |
| 版本控制 | `git_init`、`git_status`、`git_diff`、`git_commit`、`git_push`；禁用仓库钩子和不可信全局配置 |

每个成员只能访问自己的工作区。成员间消息可以协商与交接；工具结果只注入执行该工具的成员上下文，文件需要显式共享。私聊记录及私聊记忆不注入群聊。

`append_file` 每次追加最多 32 KiB，必须传入最近一次读取/写入返回的 `expected_sha256`，文件已变化则拒绝追加，避免重试重复写入。新建内置团队的文档角色拥有此工具；旧会话仍保留创建时的权限。

`read_file` 支持字符位置 `offset` / `limit`，可直接查看长文件尾部；返回的 SHA-256 始终对应完整文件。`replace_text` 根据当前哈希替换唯一匹配片段，拒绝陈旧或歧义修改，避免为小改动重写整份文件。疑似过度转义只发出提示，不擅自转换内容。`validate_file` 不执行代码，可检查 Python/JSON 语法、HTML 重复文档/ID 和日期转换风险；它不能代替功能测试。网页获取同时保留可追溯链接，减少猜测文章地址。

编排器兼容明确的工具名简写和位置放错但不冲突的工具参数，规范化后仍执行角色白名单、参数、路径和审批检查。冲突参数、多动作 JSON、未知控制字段不被猜测或静默执行。工作上下文保留最近消息和前任务摘要，完整脱敏证据仍保存在事件日志中。成员连续工作八轮后返回协调者检查进度，任务状态和预算不被自动修改。只读核查角色通过消息或评审返回意见，由可写角色保存报告。

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

2026-11-23 的最新课程任务状态、独立验收及本轮补验结果见[测试报告（中文）](docs/test-report-20261123.zh.md)与[英文版](docs/test-report-20261123.md)。早期 HKGAI 运行的域名解析故障与修复过程保留在[历史修复记录](docs/course-fix-20261123.md)；后续运行已使用 DeepSeek。

本轮最终交付为 **6/6**，原 120 回合预算内完成为 **5/6**；software-2 续跑至 198 回合完成。可直接查看[仪表盘启动说明](deliverables/course-deepseek-20261123/software-2/NOTES-dashboard.md)、[半导体 17 页修订幻灯片](deliverables/course-deepseek-20261123/fund-2/semis_deck.html)及[最终验收汇总](reports/course-deepseek-20261123/summary.json)。

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
