"""Regression tests for PR 5: modernized TUI settings/paths/workers & strict typing."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from ntcdg.config import Config
from ntcdg.models import Card
from ntcdg.storage import load_deck, save_deck
from ntcdg.tui import (
    DeckListScreen,
    NTCDGApp,
    RegenerateDialog,
    SettingsScreen,
    _decks_dir,
    _settings_file,
    load_settings,
    save_settings,
)


class TestTuiSettingsAndDynamicPaths:
    """Verify TUI honours Config.OUTPUT_DIR, merges ~/.ntcdgrc, and preserves keys."""

    def test_tui_paths_follow_config_output_dir_and_merge_rc(self, tmp_path, monkeypatch):
        out_dir = tmp_path / "custom_tui_decks"
        rc_file = tmp_path / ".ntcdgrc"
        rc_file.write_text(
            'venice_api_key: sk-from-rc\n'
            'default_text_model: deepseek-v3.2\n'
            'default_font: C:\\Fonts\\cinzel.ttf\n',
            encoding="utf-8",
        )
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(out_dir))
        monkeypatch.setattr("ntcdg.userconfig.RC_PATHS", [str(rc_file)])

        assert _decks_dir() == out_dir
        assert _settings_file() == out_dir / "ntcdg_settings.json"

        initial = load_settings()
        assert initial["venice_api_key"] == "sk-from-rc"
        assert initial["text_model"] == "deepseek-v3.2"
        assert initial["font_path"] == "C:\\Fonts\\cinzel.ttf"
        assert initial["edit_model"] == Config.DEFAULT_EDIT_MODEL

        # Saving partial settings must NOT wipe edit_model or font_path
        save_settings({"image_model": "flux-2-max"})
        after = load_settings()
        assert after["image_model"] == "flux-2-max"
        assert after["edit_model"] == Config.DEFAULT_EDIT_MODEL
        assert after["font_path"] == "C:\\Fonts\\cinzel.ttf"
        assert _settings_file().is_file()

    def test_tui_headless_mount_and_screens(self, tmp_path, monkeypatch):
        monkeypatch.setattr("ntcdg.config.Config.OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr("ntcdg.userconfig.RC_PATHS", [])

        save_deck(
            [Card(position=1, title="The Fool", card_type="Major Arcana", description="Leap")],
            "HeadlessDeck",
            export=False,
        )

        async def _exercise_app() -> None:
            app = NTCDGApp()
            async with app.run_test(size=(100, 45)) as pilot:
                await pilot.pause()
                assert isinstance(app.screen, DeckListScreen)

                # Open SettingsScreen (verifies Header() fix — no bool/str TypeError!)
                await pilot.click("#settings")
                await pilot.pause()
                assert isinstance(app.screen, SettingsScreen)

                await pilot.click("#save")
                await pilot.pause()
                assert isinstance(app.screen, DeckListScreen)
                assert Path(_settings_file()).exists()

                # Verify RegenerateDialog has background @work decorator on _run_regeneration
                dlg = RegenerateDialog("HeadlessDeck", [1])
                assert callable(dlg._run_regeneration)

        asyncio.run(_exercise_app())
        assert len(load_deck("HeadlessDeck")) == 1


class TestMypyTypecheck:
    """Ensure mypy passes cleanly across src/ntcdg in CI and local test runs."""

    def test_mypy_src_clean(self):
        pytest.importorskip("mypy")
        repo_root = Path(__file__).resolve().parent.parent
        proc = subprocess.run(
            [sys.executable, "-m", "mypy", str(repo_root / "src" / "ntcdg")],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, f"mypy failed:\n{proc.stdout}\n{proc.stderr}"

