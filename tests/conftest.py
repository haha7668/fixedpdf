import pytest

import server


@pytest.fixture(autouse=True)
def isolate_ai_configuration(tmp_path, monkeypatch):
    """Provider API tests must never read or overwrite the user's saved credentials."""
    monkeypatch.setattr(server, 'AI_CONFIG_PATH', str(tmp_path / 'ai_config.json'))
    monkeypatch.setattr(server, '_ai_config', {'providers': {}, 'order': []})
