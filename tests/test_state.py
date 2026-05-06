import json
from pathlib import Path

import pytest

from src.state import State


def test_load_returns_empty_set_when_file_missing(tmp_path):
    state = State(tmp_path / "state.json")
    assert state.completed_urls() == set()


def test_mark_done_persists_url(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.mark_done("https://example.com/a")
    state.mark_done("https://example.com/b")

    reloaded = State(path)
    assert reloaded.completed_urls() == {
        "https://example.com/a",
        "https://example.com/b",
    }


def test_mark_done_is_idempotent(tmp_path):
    state = State(tmp_path / "state.json")
    state.mark_done("https://example.com/a")
    state.mark_done("https://example.com/a")
    assert state.completed_urls() == {"https://example.com/a"}


def test_state_file_is_json_with_expected_shape(tmp_path):
    path = tmp_path / "state.json"
    state = State(path)
    state.mark_done("https://example.com/a")

    payload = json.loads(path.read_text())
    assert "completed_urls" in payload
    assert "last_updated" in payload
    assert payload["completed_urls"] == ["https://example.com/a"]
