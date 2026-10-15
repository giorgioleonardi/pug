from core import architect


def test_default_model_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("PUG_MODEL", raising=False)
    assert architect.get_model(tmp_path) == architect.DEFAULT_MODEL


def test_pug_model_env_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PUG_MODEL", "claude-test-model")
    assert architect.get_model(tmp_path) == "claude-test-model"


def test_pug_model_read_from_dotenv(monkeypatch, tmp_path):
    monkeypatch.delenv("PUG_MODEL", raising=False)
    (tmp_path / ".env").write_text('ANTHROPIC_API_KEY=x\nPUG_MODEL="claude-from-dotenv"\n')
    assert architect.get_model(tmp_path) == "claude-from-dotenv"


def test_env_var_wins_over_dotenv(monkeypatch, tmp_path):
    monkeypatch.setenv("PUG_MODEL", "claude-from-env")
    (tmp_path / ".env").write_text("PUG_MODEL=claude-from-dotenv\n")
    assert architect.get_model(tmp_path) == "claude-from-env"


def test_blank_pug_model_falls_back_to_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PUG_MODEL", "")
    (tmp_path / ".env").write_text("PUG_MODEL=\n")
    assert architect.get_model(tmp_path) == architect.DEFAULT_MODEL
