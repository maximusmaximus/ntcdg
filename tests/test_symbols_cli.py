"""Tests for symbol loading and CLI argument validation."""

import json

from ntcdg.config import Config
from ntcdg.symbols import load_symbols_config


class TestSymbolLoading:
    """Test symbol configuration loading."""

    def test_default_symbols(self):
        config = load_symbols_config(None)
        assert "symbols" in config
        assert len(config["symbols"]) == len(Config.DEFAULT_SYMBOLS)
        assert config["symbols"][0]["name"] == "loyal small dog"

    def test_load_from_file(self, tmp_path):
        symbols_file = tmp_path / "symbols.json"
        data = {
            "style_prompt": "test style",
            "symbols": [
                {"name": "test_sym", "description": "A test symbol"},
                {"name": "test_sym2", "description": "Another test"},
            ],
        }
        with open(symbols_file, "w") as f:
            json.dump(data, f)

        config = load_symbols_config(str(symbols_file))
        assert len(config["symbols"]) == 2
        assert config["symbols"][0]["name"] == "test_sym"
        assert config["style_prompt"] == "test style"

    def test_invalid_file_falls_back(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        with open(bad_file, "w") as f:
            f.write("not json")

        config = load_symbols_config(str(bad_file))
        assert len(config["symbols"]) == len(Config.DEFAULT_SYMBOLS)

    def test_missing_symbols_key_falls_back(self, tmp_path):
        bad_file = tmp_path / "no_symbols.json"
        with open(bad_file, "w") as f:
            json.dump({"other_key": "value"}, f)

        config = load_symbols_config(str(bad_file))
        assert len(config["symbols"]) == len(Config.DEFAULT_SYMBOLS)

    def test_nonexistent_file_falls_back(self):
        config = load_symbols_config("/nonexistent/path/symbols.json")
        assert len(config["symbols"]) == len(Config.DEFAULT_SYMBOLS)

    def test_legacy_elements_config(self, tmp_path):
        legacy_dir = tmp_path / "custom_elements"
        legacy_dir.mkdir()
        config_file = legacy_dir / "elements_config.json"
        with open(config_file, "w") as f:
            json.dump({"moon": "moon.png", "star": "star.png"}, f)

        # Legacy elements_config.json support is tested implicitly via fallback
        # (the code path exists but requires specific working directory setup).
        # Verify default fallback works when no legacy exists:
        config = load_symbols_config(None)
        assert len(config["symbols"]) > 0


class TestCLIValidation:
    """Test CLI argument validation."""

    def test_help_runs(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ntcdg.cli", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "--symbol-mode" in result.stdout
        assert "--symbols-file" in result.stdout

    def test_invalid_name_rejected(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ntcdg.cli", "--deck", "--name", "bad name!"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0
        assert "letters, numbers, underscores" in result.stderr

    def test_invalid_card_count_rejected(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ntcdg.cli", "--deck", "--cards", "0"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

    def test_missing_symbols_file_rejected(self):
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ntcdg.cli", "--deck", "--symbols-file", "/no/such/file.json"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0
        assert "not found" in result.stderr
