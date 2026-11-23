Have the coordinator delegate hello.md to writer. Acceptance criterion: its content must be exactly `Multi-agent collaboration verified`, with an optional trailing newline.

Writer must write and read the file, then use send_file to reviewer with destination `hello.md`. It arrives at `inbox/writer/hello.md` in the reviewer workspace. Writer then submits complete with the artifact `hello.md`.

The coordinator must message reviewer to independently read `inbox/writer/hello.md` and review the writer subtask. The coordinator may finish only after acceptance. No code execution, web search, Git operation or clarification is needed.
