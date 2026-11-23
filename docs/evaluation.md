# 评测方法与数据格式

## 指标定义

| 指标 | 口径 |
|---|---|
| `elapsed_seconds` | 从任务分配到最终结果的墙钟时间，包含等待人类的时间；等待中的值会随读取状态更新 |
| `active_seconds` | 引擎实际运行、API 请求、工具和复盘的时间，不计人类等待 |
| `agent_turns` | 已尝试的模型动作回合，包含无效协议及失败请求 |
| `subtask_completion_rate` | 审核通过的子任务数 / 所有委派尝试数；失败重试仍在分母 |
| `model_claimed_success` | 协调者最终声称成功与否 |
| `peer_reviewed_completion` | 当前所有有效子任务经不同成员审核通过，并由协调者完成 |
| `fatal_errors` | 导致任务停止的运行时、模型请求或连续协议错误；普通工具失败单独计入 `tool_errors` |
| `verified_task_completion_rate` | 总任务已完成且全部独立规则通过的案例数 / 全部案例数；无独立规则的案例不自动计为通过 |

完成率以 0–1 保存，报告中显示百分比。人工审批等待、预算耗尽、未执行的后续任务均不算成功。开放题必须补充人工评分，不能把保守的自动验证率直接当成最终综合成绩。

## 测试集

```json
{
  "cases": [
    {
      "id": "task-1",
      "session": "same-team",
      "scenario": "software",
      "task": "Write a short Markdown report and have it independently reviewed.",
      "human_responses": ["The target audience is first-year students."],
      "checks": [
        {"type":"file_exists","agent":"dev","path":"report.md"},
        {"type":"text_contains","agent":"dev","path":"report.md","text":"Sources"}
      ]
    }
  ]
}
```

`id` 唯一；相同 `session` 会复用团队、记忆和文件，必须使用相同 `scenario`。独立规则支持 `file_exists`、`text_contains`、`text_equals`，不能执行测试集中任意 Python 或 shell。严格相等只忽略末尾换行。

`human_responses` 只回答普通澄清问题，**不会批准工具**。如果前一项仍在等待或预算耗尽，同 session 后续案例记录 `blocked_by_previous_case`。不同 session 继续运行。测试集语法和规则在产生模型费用前验证。

## 产物与人工评审

`results.json` 提供逐案例结果、指标、独立验收结果、前后记忆统计及未决请求；`report.md` 提供汇总；`sessions/` 包含详细事件和工作文件。

新闻报道、投资分析和完整软件需要人工根据任务要求核验内容与可用性。建议保留以下证据：任务原文、真实澄清与审批、运行/测试输出、资料来源、最终产物、失败原因、修复记录，以及下一个任务是否正确复用了记忆。此项目没有为未发布的最终测试集虚构成绩。

## 已有验证范围

单元与集成测试全部使用临时目录、假模型和必要的本机隔离执行，不依赖外部模型费用。覆盖审批与恢复、私聊隔离、路径攻击、网络目标检查、Git 配置攻击、真实 macOS 沙箱、记忆检索、独立验收及顺序任务。

真实 HKGAI 小型协作评测的结果另见 `validation.md`。它验证连通性与工作流，不代表三组课程开放任务或最终保密测试集的成绩。
