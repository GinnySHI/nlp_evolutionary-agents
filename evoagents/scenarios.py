"""Course scenarios and a small independently checkable local smoke task."""
from __future__ import annotations

SCENARIOS = {
    "software": {
        "title": "Software Development Team",
        "agents": [
            {"id": "lead", "name": "技术负责人", "role": "理解用户目标，协调技术方案、团队分工与交付；与用户讨论问题与取舍。"},
            {"id": "dev", "name": "软件开发工程师", "role": "将需求实现为可运行软件，解决技术问题，根据用户与团队反馈改进。"},
            {"id": "qa", "name": "测试工程师", "role": "从用户角度验证软件，设计有意义的测试，发现问题并核验修复；独立评审交付。"},
            {"id": "release", "name": "发布经理", "role": "负责版本控制、运行方法、交付物和发布说明；执行提交或推送前请求明确许可。"},
        ],
        "tasks": [
            "我们目前使用共享表格管理会议室，经常出现重复预订和取消后记录未更新的问题。请构建可用的会议室预订系统，支持查看空闲、预订和取消。展示成果并说明使用方法。有不清楚的工作规则时，请在群里询问我。",
            "在此前的会议室预订系统上增加面向管理员的交互式使用情况仪表盘。支持选择日期范围，展示每间会议室的预订次数、预订总时长、最繁忙的日期和时段、取消频率。使用系统真实的预订记录，以清晰图表和汇总帮助管理员调整资源分配。需求不清楚时请询问我。",
        ],
    },
    "newsroom": {
        "title": "Newsroom",
        "agents": [
            {"id": "chief_editor", "name": "总编辑", "role": "负责选题、报道角度、质量和团队协调，与需求方讨论编辑判断。"},
            {"id": "reporter", "name": "记者", "role": "寻找近期新闻线索，调查事实和来源，不虚构采访、引语或证据。"},
            {"id": "fact_checker", "name": "事实核查员", "role": "独立检查事实、来源和主张，指出证据不足、冲突和不确定性。"},
            {"id": "editor", "name": "编辑", "role": "组织润色文章，根据受众和渠道调整表达，保留来源和不确定性。"},
        ],
        "tasks": [
            "面向香港科技大学师生，以‘港科大校园中的 AI’为主题，自行选择一个近期、具体、有报道价值的事件，开展调查并准备适合不同渠道发布的报道，解释发生了什么及其意义。可以与我讨论选题和受众需求。交付 Markdown，不自行对外发布。",
            "请调查‘AI 写作检测工具能可靠判断大学生作业是否由 AI 撰写’这一说法。审查证据，为学生和教师撰写事实核查文章，解释结论及尚存的不确定性。可以讨论主张含义、编辑角度和过程中的问题。",
        ],
    },
    "fund": {
        "title": "Securities Investment Fund Team",
        "agents": [
            {"id": "fund_manager", "name": "基金经理", "role": "设定投资目标，综合研究、风险和客户需求形成模拟方案，说明取舍。"},
            {"id": "research", "name": "投资研究员", "role": "研究市场、行业、证券，以可追溯证据支持判断，不捏造行情。"},
            {"id": "risk", "name": "风险经理", "role": "独立评估风险、投资期限和风险承受能力，检查配置的适配性和风险管理。"},
            {"id": "marketing", "name": "营销专员", "role": "了解客户需求，向团队传达，用客户理解的语言解释模拟方案及风险。"},
        ],
        "tasks": [
            "我今年25岁，有100万港元，希望投资美股。请研究并制定模拟投资方案，解释配置理由和风险，准备易懂的介绍。可以询问我的投资目标、期限和风险偏好。这是模拟研究，不执行交易。",
            "以2026年底的视角，研究半导体行业未来，为基金团队制作可以在浏览器逐页播放的 HTML 幻灯片，说明投资含义和关键风险。自行决定研究范围、结构和设计，可以向我澄清需求。严格区分已发生事实和未来预测，不虚构未来数据。注意课程总说明限定文档为 md/txt，而本任务明确要求 HTML；先向真人确认该格式冲突。",
        ],
    },
    "smoke": {
        "title": "Collaboration Smoke Test",
        "agents": [
            {"id": "lead", "name": "协调员", "role": "分派工作，安排独立评审并汇总交付。此任务需求明确，不需额外提问。"},
            {"id": "writer", "name": "编写员", "role": "在自己的工作区写文件并读取核验，向审核员共享文件。"},
            {"id": "reviewer", "name": "审核员", "role": "独立读取共享文件，按明确标准审核并给出评审。"},
            {"id": "recorder", "name": "记录员", "role": "记录可复用的协作经验，必要时帮助审核。"},
        ],
        "tasks": [
            "Have the coordinator delegate hello.md to writer. Acceptance criterion: its content must be exactly 'Multi-agent collaboration verified', with an optional trailing newline. Writer must write and read the file, then send_file to reviewer with destination hello.md; it arrives at inbox/writer/hello.md in the reviewer workspace. After writer submits complete, the coordinator messages reviewer to independently read inbox/writer/hello.md and review the writer subtask. The coordinator may finish only after acceptance. No code execution, web search, Git operation or clarification is needed.",
        ],
    },
}


def scenario(name: str) -> dict:
    if name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {name}; choose from {', '.join(SCENARIOS)}")
    return SCENARIOS[name]
