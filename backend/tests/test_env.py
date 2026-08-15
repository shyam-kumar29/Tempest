from __future__ import annotations

import os

from tempest.env import load_env_file


def test_load_env_file_sets_missing_values_only(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text(
        "\n".join(
            [
                "# local secrets",
                "OPENAI_API_KEY=from-file",
                "TEMPEST_AI_MODEL='gpt-5-mini'",
                "EXISTING=value-from-file",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TEMPEST_AI_MODEL", raising=False)
    monkeypatch.setenv("EXISTING", "from-env")

    loaded = load_env_file(env_path)

    assert loaded == ["OPENAI_API_KEY", "TEMPEST_AI_MODEL"]
    assert os.environ["OPENAI_API_KEY"] == "from-file"
    assert os.environ["TEMPEST_AI_MODEL"] == "gpt-5-mini"
    assert os.environ["EXISTING"] == "from-env"
