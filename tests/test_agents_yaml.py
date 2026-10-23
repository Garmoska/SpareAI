"""YAML agents-file loader."""
from __future__ import annotations

import pytest

from spareai.dispatcher.config import _load_agents_yaml


def test_loads_valid_file(tmp_path):
    p = tmp_path / "agents.yaml"
    p.write_text("agents:\n  - node_id: a\n    url: http://1.1.1.1:8081\n"
                 "  - node_id: b\n    url: http://2.2.2.2:8081/\n")
    out = _load_agents_yaml(p)
    assert [a.node_id for a in out] == ["a", "b"]
    assert out[1].url == "http://2.2.2.2:8081"  # trailing slash stripped


def test_rejects_duplicate_node_id(tmp_path):
    p = tmp_path / "agents.yaml"
    p.write_text("agents:\n  - node_id: a\n    url: http://1\n"
                 "  - node_id: a\n    url: http://2\n")
    with pytest.raises(RuntimeError, match="Duplicate"):
        _load_agents_yaml(p)


def test_rejects_missing_fields(tmp_path):
    p = tmp_path / "agents.yaml"
    p.write_text("agents:\n  - node_id: a\n")
    with pytest.raises(RuntimeError, match="Invalid"):
        _load_agents_yaml(p)


def test_rejects_missing_file(tmp_path):
    with pytest.raises(RuntimeError, match="not found"):
        _load_agents_yaml(tmp_path / "nope.yaml")
