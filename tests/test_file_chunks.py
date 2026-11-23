"""Chunked writes keep retry behavior, content hashes and isolation explicit."""
import hashlib
import os

import pytest

from evoagents.tools import MAX_APPEND_BYTES, MAX_FILE_BYTES, ToolRunner


@pytest.fixture
def runner(tmp_path):
    return ToolRunner(tmp_path / "agents", agent_ids=["writer", "reviewer"])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def append(runner, content, expected, path="report.md"):
    return runner.execute("writer", "append_file", {
        "path": path, "content": content, "expected_sha256": expected,
    })


def test_unicode_chunks_and_retry_cannot_append_twice(runner):
    first = runner.execute("writer", "write_file", {"path": "report.md", "content": "第一段\n"})
    second = append(runner, "Second part\n", first["sha256"])
    assert second["ok"]
    assert second["appended_bytes"] == len(b"Second part\n")
    expected = "第一段\nSecond part\n".encode()
    assert second["bytes"] == len(expected)
    assert second["sha256"] == digest(expected)
    duplicate = append(runner, "Second part\n", first["sha256"])
    assert duplicate["ok"] is False and "precondition" in duplicate["error"]
    read = runner.execute("writer", "read_file", {"path": "report.md"})
    assert read["content"].encode() == expected
    assert read["sha256"] == second["sha256"]
    assert read["bytes"] == len(expected)
    assert not runner.execute("reviewer", "read_file", {"path": "report.md"})["ok"]


def test_read_hash_covers_full_file_even_if_content_is_truncated(runner):
    data = "a" * 70_000
    initial = runner.execute("writer", "write_file", {"path": "report.md", "content": data})
    read = runner.execute("writer", "read_file", {"path": "report.md"})
    assert read["truncated"] and read["sha256"] == initial["sha256"]
    assert read["bytes"] == 70_000
    assert append(runner, "tail", read["sha256"])["ok"]


def test_append_size_limits_preserve_original(runner):
    original = "x" * (MAX_FILE_BYTES - 1)
    first = runner.execute("writer", "write_file", {"path": "report.md", "content": original})
    for chunk in ("", "z" * (MAX_APPEND_BYTES + 1), "世界"):
        assert not append(runner, chunk, first["sha256"])["ok"]
    assert (runner.workspace("writer") / "report.md").read_text() == original
    assert append(runner, "z", first["sha256"])["ok"]


@pytest.mark.parametrize("expected", ["", "invalid", "A" * 64, "0" * 64])
def test_append_requires_actual_hash(runner, expected):
    runner.execute("writer", "write_file", {"path": "report.md", "content": "data"})
    assert not append(runner, "tail", expected)["ok"]
    assert (runner.workspace("writer") / "report.md").read_text() == "data"


def test_append_requires_existing_file_and_exact_arguments(runner):
    assert not append(runner, "tail", digest(b""))["ok"]
    assert not (runner.workspace("writer") / "report.md").exists()
    assert not runner.execute("writer", "append_file", {"path": "report.md", "content": "tail"})["ok"]
    assert not append(runner, "tail", digest(b""), "../reviewer/workspace/report.md")["ok"]


def test_append_rejects_links_and_special_files(runner, tmp_path):
    original = tmp_path / "original.md"
    original.write_text("secret")
    space = runner.workspace("writer")
    (space / "link.md").symlink_to(original)
    os.link(original, space / "hard.md")
    os.mkfifo(space / "fifo.md")
    (space / "escape").symlink_to(tmp_path, target_is_directory=True)
    for name in ("link.md", "hard.md", "fifo.md", "escape/original.md"):
        assert not append(runner, "tail", digest(b"secret"), name)["ok"]
    assert original.read_text() == "secret"


def test_append_rejects_changed_target_before_atomic_replace(runner, monkeypatch):
    initial = runner.execute("writer", "write_file", {"path": "report.md", "content": "initial"})
    original_fsync = os.fsync
    def concurrent_write(fd):
        original_fsync(fd)
        (runner.workspace("writer") / "report.md").write_text("external update")
    monkeypatch.setattr(os, "fsync", concurrent_write)
    result = append(runner, "tail", initial["sha256"])
    assert not result["ok"] and "changed" in result["error"]
    assert (runner.workspace("writer") / "report.md").read_text() == "external update"
    assert not list(runner.workspace("writer").glob(".tool-*.tmp"))


def replace(runner, old, new, expected, path='report.md'):
    return runner.execute('writer', 'replace_text', {'path':path, 'old':old, 'new':new, 'expected_sha256':expected})


def test_replace_unicode_unique_span_and_stale_retry(runner):
    first = runner.execute('writer','write_file',{'path':'report.md','content':'标题\nOld text\nEnd'})
    edited = replace(runner,'Old text','新内容',first['sha256'])
    assert edited['ok'] and edited['replacements'] == 1
    assert edited['sha256'] == digest('标题\n新内容\nEnd'.encode())
    assert not replace(runner,'Old text','新内容',first['sha256'])['ok']
    assert (runner.workspace('writer')/'report.md').read_text() == '标题\n新内容\nEnd'


def test_replace_rejects_overlapping_ambiguous_matches(runner):
    first = runner.execute('writer', 'write_file', {'path':'report.md', 'content':'aaa'})
    assert not replace(runner, 'aa', 'b', first['sha256'])['ok']
    assert (runner.workspace('writer')/'report.md').read_text() == 'aaa'


@pytest.mark.parametrize('old,new', [('', 'x'), ('missing','x'), ('twice','x'), ('x'*32769,'x'), ('tail','x'*32769)])
def test_replace_rejects_ambiguous_or_oversized_spans(runner,old,new):
    first=runner.execute('writer','write_file',{'path':'report.md','content':'twice twice tail'})
    assert not replace(runner,old,new,first['sha256'])['ok']
    assert (runner.workspace('writer')/'report.md').read_text() == 'twice twice tail'


def test_replace_links_races_and_total_limit(runner,tmp_path,monkeypatch):
    original=tmp_path/'outside.md';original.write_text('outside')
    space=runner.workspace('writer')
    (space/'link.md').symlink_to(original)
    os.link(original,space/'hard.md')
    for name in ('link.md','hard.md','../escape.md'):
        assert not replace(runner,'outside','changed',digest(b'outside'),name)['ok']
    assert original.read_text()=='outside'
    first=runner.execute('writer','write_file',{'path':'report.md','content':'x'*(MAX_FILE_BYTES-1)+'!'})
    assert not replace(runner,'!','two',first['sha256'])['ok']
    initial=runner.execute('writer','write_file',{'path':'report.md','content':'initial'})
    real_fsync=os.fsync
    def racing(fd):
        real_fsync(fd)
        (space/'report.md').write_text('external')
    monkeypatch.setattr(os,'fsync',racing)
    assert not replace(runner,'initial','edited',initial['sha256'])['ok']
    assert (space/'report.md').read_text()=='external'


def test_paged_read_keeps_full_hash_and_can_inspect_footer(runner):
    text='中文'+('x'*70000)+'footer'
    first=runner.execute('writer','write_file',{'path':'report.md','content':text})
    read=runner.execute('writer','read_file',{'path':'report.md','offset':70002,'limit':6})
    assert read['content']=='footer' and read['next_offset'] is None
    assert read['truncated'] and read['sha256']==first['sha256']
    assert read['total_chars']==len(text)
    partial=runner.execute('writer','read_file',{'path':'report.md','limit':5})
    assert partial['next_offset']==5
    assert not runner.execute('writer','read_file',{'path':'report.md','offset':-1})['ok']


def test_literal_escapes_warn_without_modifying_content(runner):
    content=('paragraph literal \\n '*20)
    result=runner.execute('writer','write_file',{'path':'report.md','content':content})
    assert 'warning' in result
    assert (runner.workspace('writer')/'report.md').read_text()==content
    actual=runner.execute('writer','write_file',{'path':'report.md','content':content.replace('\\n','\n')})
    assert 'warning' not in actual
