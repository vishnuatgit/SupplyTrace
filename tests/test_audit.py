import json

from src.utils.audit import append_audit_entries, read_audit_entries


def test_entries_are_appended_as_json_lines(tmp_path):
    path = tmp_path / "logs" / "audit_log.jsonl"
    assert append_audit_entries(str(path), [{"n": 1}, {"n": 2}])
    assert append_audit_entries(str(path), [{"n": 3}])
    assert [json.loads(line)["n"] for line in path.read_text().splitlines()] == [1, 2, 3]


def test_log_is_rotated_once_it_reaches_the_cap(tmp_path):
    path = tmp_path / "audit_log.jsonl"
    for n in range(10):
        append_audit_entries(str(path), [{"n": n, "pad": "x" * 40}], max_bytes=200)

    rotated = tmp_path / "audit_log.jsonl.1"
    assert rotated.exists()
    # Disk use stays bounded: the live log and one rotated copy, each about max_bytes.
    assert path.stat().st_size < 200 + 100
    assert rotated.stat().st_size < 200 + 100
    assert json.loads(path.read_text().splitlines()[-1])["n"] == 9


def test_write_failure_is_reported_not_raised(tmp_path):
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("a file where a directory should be")
    assert append_audit_entries(str(blocker / "audit_log.jsonl"), [{"n": 1}]) is False


def test_entries_are_read_newest_first_with_their_lines(tmp_path):
    path = tmp_path / "audit_log.jsonl"
    append_audit_entries(str(path), [{"n": 1}, {"n": 2}])
    with open(path, "a", encoding="utf-8") as f:
        f.write("not json\n[1, 2]\n\n")  # a broken line, a non-object, a blank line
    append_audit_entries(str(path), [{"n": 3}])

    entries = read_audit_entries(str(path))
    assert [entry["n"] for entry, _ in entries] == [3, 2, 1]
    assert entries[0][1] == '{"n": 3}'


def test_missing_log_reads_as_empty(tmp_path):
    assert read_audit_entries(str(tmp_path / "none.jsonl")) == []
