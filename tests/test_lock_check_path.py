import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from lock_check import path_within_declaration

def test_exact_file_within_dir(tmp_path):
    f = tmp_path / "src" / "app.py"
    d = tmp_path / "src"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is True

def test_deep_nesting(tmp_path):
    f = tmp_path / "src" / "api" / "routes" / "user.ts"
    d = tmp_path / "src" / "api"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is True

def test_regression_api_vs_api_keys(tmp_path):
    # THE critical regression: src/api must NOT match src/api-keys/secrets.ts
    f = tmp_path / "src" / "api-keys" / "secrets.ts"
    d = tmp_path / "src" / "api"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is False

def test_sibling_dir_not_matched(tmp_path):
    f = tmp_path / "tests" / "test_routes.py"
    d = tmp_path / "src"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is False

def test_declared_equals_target(tmp_path):
    f = tmp_path / "src" / "app.py"
    assert path_within_declaration(str(f), str(f), str(tmp_path)) is True

def test_relative_declared_path(tmp_path):
    f = tmp_path / "src" / "api" / "user.ts"
    assert path_within_declaration(str(f), "src/api", str(tmp_path)) is True

def test_target_is_parent_of_declared(tmp_path):
    # target is shallower than declared — should be False
    f = tmp_path / "src"
    d = tmp_path / "src" / "api"
    assert path_within_declaration(str(f), str(d), str(tmp_path)) is False
