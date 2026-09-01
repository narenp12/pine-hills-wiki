"""Tests for load_bible error handling."""
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import scripts.generate


class DummyYAMLError(Exception):
    pass


class DummyYAML:
    YAMLError = DummyYAMLError

    @staticmethod
    def safe_load(text):
        raise DummyYAMLError("bad yaml")


def test_load_bible_malformed(tmp_path, capsys, monkeypatch):
    # Create a dummy bible.yaml with invalid content
    bad_yaml = tmp_path / "bible.yaml"
    bad_yaml.write_text("!invalid: yaml")

    # Monkeypatch BIBLE_PATH
    monkeypatch.setattr(scripts.generate, "BIBLE_PATH", bad_yaml)

    # Monkeypatch yaml module to simulate parse error
    dummy_yaml = DummyYAML()
    monkeypatch.setattr(scripts.generate, "yaml", dummy_yaml)

    # Call load_bible
    result = scripts.generate.load_bible()

    # Should return empty dict on parse error
    assert result == {}

    # Should print error to stderr
    captured = capsys.readouterr()
    assert "Failed to parse bible.yaml" in captured.err


def test_load_bible_missing_file(tmp_path, capsys, monkeypatch):
    # Point to a non-existent file
    missing = tmp_path / "nonexistent.yaml"
    monkeypatch.setattr(scripts.generate, "BIBLE_PATH", missing)

    # Ensure yaml module is available (real yaml if installed, otherwise dummy)
    # If real yaml not installed, we can just leave it as is; load_bible will handle None
    # But to test missing file path, we just need to ensure yaml is not None? Actually load_bible returns {} early if file doesn't exist.
    result = scripts.generate.load_bible()
    assert result == {}
    # No error message expected for missing file (it's silent)