from __future__ import annotations

import os
from pathlib import Path

from after_sales_agent.config import environment as env_loader


def test_env_loader_preserves_existing_environment_when_override_is_false(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=file-model\nNEW_SETTING=loaded\n", encoding="utf-8")
    monkeypatch.setattr(env_loader, "__file__", str(tmp_path / "env_loader.py"))
    monkeypatch.setenv("LLM_MODEL", "deployment-model")
    monkeypatch.delenv("NEW_SETTING", raising=False)
    assert env_loader.load_agent_env(override=False) == env_file
    assert os.environ["LLM_MODEL"] == "deployment-model"
    assert os.environ["NEW_SETTING"] == "loaded"


def test_env_loader_overrides_existing_environment_by_default(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setattr(env_loader, "__file__", str(tmp_path / "env_loader.py"))
    monkeypatch.setenv("LLM_MODEL", "deployment-model")

    assert env_loader.load_agent_env() == env_file
    assert os.environ["LLM_MODEL"] == "file-model"


def test_env_loader_can_preserve_deployment_environment(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("LLM_MODEL=file-model\n", encoding="utf-8")
    monkeypatch.setattr(env_loader, "__file__", str(tmp_path / "env_loader.py"))
    monkeypatch.setenv("LLM_MODEL", "deployment-model")

    assert env_loader.load_agent_env(override=False) == env_file
    assert os.environ["LLM_MODEL"] == "deployment-model"
