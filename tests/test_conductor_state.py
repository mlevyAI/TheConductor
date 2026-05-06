import json, os, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
import conductor_state

def make_state(tmpdir, fields):
    d = Path(tmpdir) / ".conductor"
    d.mkdir(exist_ok=True)
    (d / "state.json").write_text(json.dumps(fields))

def test_read_state_returns_none_when_absent(tmp_path):
    assert conductor_state.read_state(str(tmp_path)) is None

def test_read_state_returns_dict(tmp_path):
    make_state(tmp_path, {"phase": "1", "gate": "post_first_response_proceed"})
    s = conductor_state.read_state(str(tmp_path))
    assert s["phase"] == "1"
    assert s["gate"] == "post_first_response_proceed"

def test_get_phase_returns_none_when_absent(tmp_path):
    assert conductor_state.get_phase(str(tmp_path)) is None

def test_get_phase_returns_value(tmp_path):
    make_state(tmp_path, {"phase": "0"})
    assert conductor_state.get_phase(str(tmp_path)) == "0"

def test_get_gate_returns_value(tmp_path):
    make_state(tmp_path, {"phase": "1", "gate": "pre_first_response_proceed"})
    assert conductor_state.get_gate(str(tmp_path)) == "pre_first_response_proceed"

def test_get_gate_returns_none_when_absent(tmp_path):
    assert conductor_state.get_gate(str(tmp_path)) is None

def test_migrate_adds_gate_and_scaffold_written(tmp_path):
    make_state(tmp_path, {"phase": "2"})
    conductor_state.migrate_state_if_needed(str(tmp_path))
    s = conductor_state.read_state(str(tmp_path))
    assert "gate" in s
    assert "scaffold_written" in s
    assert s["gate"] == "post_first_response_proceed"
    assert s["scaffold_written"] is False

def test_migrate_is_idempotent(tmp_path):
    make_state(tmp_path, {"phase": "2", "gate": "my_gate", "scaffold_written": True})
    conductor_state.migrate_state_if_needed(str(tmp_path))
    s = conductor_state.read_state(str(tmp_path))
    assert s["gate"] == "my_gate"
    assert s["scaffold_written"] is True

def test_migrate_creates_backup(tmp_path):
    make_state(tmp_path, {"phase": "2"})
    conductor_state.migrate_state_if_needed(str(tmp_path))
    bak = tmp_path / ".conductor" / "state.json.v4.1.bak"
    assert bak.exists()

def test_validate_scaffold_delegate_pass():
    fm = {"skills": ["conductor-scaffold-ai-director-os"], "tools": ["Read", "Write", "Edit", "Bash"]}
    assert conductor_state.validate_scaffold_delegate(fm) is True

def test_validate_scaffold_delegate_missing_skill():
    fm = {"skills": [], "tools": ["Read", "Write", "Edit", "Bash"]}
    assert conductor_state.validate_scaffold_delegate(fm) is False

def test_validate_scaffold_delegate_missing_tool():
    fm = {"skills": ["conductor-scaffold-ai-director-os"], "tools": ["Read", "Write", "Edit"]}
    assert conductor_state.validate_scaffold_delegate(fm) is False

def test_validate_scaffold_delegate_string_fields():
    fm = {"skills": "conductor-scaffold-ai-director-os", "tools": "Read, Write, Edit, Bash"}
    assert conductor_state.validate_scaffold_delegate(fm) is True

def test_validate_scaffold_delegate_non_dict():
    assert conductor_state.validate_scaffold_delegate(None) is False
    assert conductor_state.validate_scaffold_delegate("not a dict") is False
