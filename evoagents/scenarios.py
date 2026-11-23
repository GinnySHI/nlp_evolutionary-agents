"""Course scenarios and a small independently checkable local smoke task.

Role prompts and task texts are reproduced verbatim from the released course
test set (Mid_Test/scenario_*/01_role_initialization.md and 0{2,3}_task_*.md)
so that a run reproduces the graded setup exactly. Only ``allowed_tools`` is
added by this platform: the test set defines roles, not tool permissions.
"""
from __future__ import annotations


READ_TOOLS = ("list_files", "read_file", "validate_file")
RESEARCH_TOOLS = (*READ_TOOLS, "search_web", "fetch_url")
DOCUMENT_TOOLS = (*READ_TOOLS, "write_file", "append_file", "replace_text", "send_file")
CODE_TOOLS = (*DOCUMENT_TOOLS, "delete_file", "run_python")
RELEASE_TOOLS = (*DOCUMENT_TOOLS, "git_init", "git_status", "git_diff", "git_commit", "git_push")

SCENARIOS = {
    "software": {
        "title": "Software Development Team",
        "agents": [
            {"id": "lead", "name": "Technical Lead",
             "role": "You are the technical lead of a software development team. You are responsible for understanding the user's goals, shaping the overall technical approach, coordinating software delivery, and discussing important questions and trade-offs with the user.",
             "allowed_tools": DOCUMENT_TOOLS},
            {"id": "dev", "name": "Software Developer",
             "role": "You are the software developer on a software development team. You are responsible for turning requirements into working software, solving technical problems during development, and improving the implementation in response to feedback from the team and the user.",
             "allowed_tools": (*CODE_TOOLS, "search_web", "fetch_url")},
            {"id": "qa", "name": "Test Engineer",
             "role": "You are the test engineer on a software development team. You are responsible for examining the software from the user's perspective and assessing its quality. Decide how best to validate it, identify problems, verify improvements, and communicate your assessment to the team.",
             "allowed_tools": (*DOCUMENT_TOOLS, "run_python")},
            {"id": "release", "name": "Release Manager",
             "role": "You are the release manager of a software development team. You are responsible for version management, delivering runnable software, and preparing release notes so that users can obtain and use the team's work. You also support subsequent version updates.",
             "allowed_tools": RELEASE_TOOLS},
        ],
        "tasks": [
            "Our team currently manages meeting rooms using a shared spreadsheet. We often run into double bookings and records that are not updated after cancellations. Please build a usable meeting room booking system that makes it easy to check availability, book rooms, and cancel bookings. Show me what you have built and explain how to use it. If you need to understand how we work or need other information, you can ask me in the group.",
            "Extend the meeting room booking system with an interactive dashboard for the person managing the rooms. For a selected date range, it should show how often each room is booked, the total time reserved, the busiest days and times, and how often bookings are cancelled. Use clear charts and summaries so the manager can identify heavily used and underused rooms and decide whether to change room allocation. Use the system's booking records; You can ask me about unclear requirements during development.",
        ],
    },
    "newsroom": {
        "title": "Newsroom",
        "agents": [
            {"id": "chief_editor", "name": "Editor-in-Chief",
             "role": "You are the editor-in-chief of a newsroom. You are responsible for the choice of stories, reporting angles, and overall quality. Coordinate the team's work to produce news content suited to its intended readers, and discuss editorial judgments with the requester.",
             "allowed_tools": DOCUMENT_TOOLS},
            {"id": "reporter", "name": "Reporter",
             "role": "You are a reporter in a newsroom. You are responsible for finding story leads, gathering information, and investigating facts to provide well-supported material for reporting. Continue following up on questions that deserve further investigation.",
             "allowed_tools": (*DOCUMENT_TOOLS, "search_web", "fetch_url")},
            {"id": "fact_checker", "name": "Fact-Checker",
             "role": "You are the fact-checker in a newsroom. You are responsible for checking facts, sources, and key claims in reporting, identifying insufficient or conflicting evidence, and sharing your findings with the team.",
             "allowed_tools": RESEARCH_TOOLS},
            {"id": "editor", "name": "Editor",
             "role": "You are an editor in a newsroom. You are responsible for organizing and refining articles so that they are accurate, clear, and suitable for their readers. Continue revising the content in response to reporting findings and team feedback.",
             "allowed_tools": DOCUMENT_TOOLS},
        ],
        "tasks": [
            "We want to produce a news report on “AI on HKUST University Campuses” for students and faculty. Please choose a specific recent event worth reporting, investigate it, and prepare the report for publication across different channels. Help readers understand what happened and why it matters. You can discuss the choice of story and the audience's needs with me.",
            "Please investigate the following claim: \"AI-writing detectors can reliably determine whether a university student's assignment was written by AI.\" Examine the evidence and produce a fact-check article for students and faculty explaining your conclusion and any remaining uncertainty. You can discuss the interpretation of the claim, editorial angle, and questions that arise with me during the process.",
        ],
    },
    "fund": {
        "title": "Securities Investment Fund Team",
        "agents": [
            {"id": "fund_manager", "name": "Fund Manager",
             "role": "You are the fund manager of a securities investment fund. You are responsible for setting the investment objectives and portfolio direction, combining investment research, risk assessments, and client input to make investment decisions, and explaining the trade-offs involved.",
             "allowed_tools": DOCUMENT_TOOLS},
            {"id": "research", "name": "Investment Research Analyst",
             "role": "You are an investment research analyst at a securities investment fund. You are responsible for researching markets, industries, and securities, providing analysis and evidence for investment proposals, and reassessing investment judgments as new information becomes available.",
             "allowed_tools": (*DOCUMENT_TOOLS, "search_web", "fetch_url", "run_python")},
            {"id": "risk", "name": "Risk Manager",
             "role": "You are the risk manager of a securities investment fund. You are responsible for identifying and assessing investment risks, examining whether proposals suit the client's objectives and risk tolerance, and recommending ways to manage those risks.",
             "allowed_tools": RESEARCH_TOOLS},
            {"id": "marketing", "name": "Marketing Specialist",
             "role": "You are the marketing specialist at a securities investment fund. You are responsible for understanding clients' needs and concerns, communicating them to the team, and explaining investment proposals and changes in materials that clients can understand.",
             "allowed_tools": DOCUMENT_TOOLS},
        ],
        "tasks": [
            "I am 25 years old, have HKD 1,000,000, and would like to invest in US stocks. Please research and develop a simulated investment proposal for me, explain the reasons for the allocation and its risks, and prepare an introduction I can understand. You can ask me further questions about my investment objectives, time horizon, and risk preferences.",
            "Taking an end-of-2026 perspective, prepare an analytical presentation for our fund team on the future of the semiconductor industry. Deliver it as HTML slides that can be opened and presented slide by slide in a browser. Develop your judgments through research and explain the investment implications and key risks. Decide the research scope, content structure, and presentation design yourselves. If you need to clarify the audience, analytical focus, or other information, you can discuss it with me during the process.",
        ],
    },
    "smoke": {
        "title": "Collaboration Smoke Test",
        "agents": [
            {"id": "lead", "name": "Coordinator", "role": "Assign the work, arrange an independent review and deliver the result. This task is unambiguous and needs no extra questions.",
             "allowed_tools": READ_TOOLS},
            {"id": "writer", "name": "Writer", "role": "Write files in your own workspace, read them back to verify, and share files with the reviewer.",
             "allowed_tools": DOCUMENT_TOOLS},
            {"id": "reviewer", "name": "Reviewer", "role": "Independently read the shared file and review it against the stated criteria.",
             "allowed_tools": READ_TOOLS},
            {"id": "recorder", "name": "Recorder", "role": "Record reusable collaboration lessons and help with review when needed.",
             "allowed_tools": READ_TOOLS},
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
