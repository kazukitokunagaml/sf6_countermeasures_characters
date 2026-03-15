import tempfile
import unittest
from pathlib import Path

from app import normalize_character_name, parse_matchup_notes, patch_config


class NormalizeCharacterNameTests(unittest.TestCase):
    def test_normalizes_japanese_and_english_aliases(self) -> None:
        self.assertEqual(normalize_character_name("豪鬼"), "AKUMA")
        self.assertEqual(normalize_character_name("Gouki"), "AKUMA")
        self.assertEqual(normalize_character_name("aki"), "A.K.I.")
        self.assertEqual(normalize_character_name("春麗"), "CHUN-LI")
        self.assertEqual(normalize_character_name("e. honda"), "E. HONDA")


class ParseMatchupNotesTests(unittest.TestCase):
    def test_parses_markdown_files_per_character(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AKUMA.md").write_text(
                "# header\n\n百鬼対策: 前ジャンプ。\n\n画面端: インパクト。\n",
                encoding="utf-8",
            )
            (root / "A.K.I.md").write_text("弾対策: 空ジャンプ。\n", encoding="utf-8")

            notes = parse_matchup_notes(root)

            self.assertEqual(notes["AKUMA"].opponent, "AKUMA")
            self.assertEqual(notes["AKUMA"].bullets, ["百鬼対策: 前ジャンプ。", "画面端: インパクト。"])
            self.assertEqual(notes["A.K.I."].bullets, ["弾対策: 空ジャンプ。"])


class PatchConfigTests(unittest.TestCase):
    def test_updates_capture_regions_and_primary_region(self) -> None:
        current = {
            "self_character": "RYU",
            "capture_region": {"left": 1, "top": 2, "width": 3, "height": 4},
            "capture_regions": [{"name": "OLD", "left": 1, "top": 2, "width": 3, "height": 4, "enabled": True, "ocr": True}],
            "poll_seconds": 0.75,
            "min_confidence": 0.72,
            "web_port": 8765,
            "capture_backend": "auto",
            "ocr_enabled": True,
            "ocr_weight": 0.35,
            "debug_save_images": True,
            "obs_mode": False,
            "overlay_click_through": False,
            "overlay_window": {"x": 40, "y": 40, "width": 540, "height": 360},
        }
        patch = {
            "capture_regions": [
                {"name": "hud", "left": 10, "top": 20, "width": 300, "height": 80, "enabled": True, "ocr": False}
            ],
            "obs_mode": True,
        }

        merged = patch_config(current, patch)

        self.assertEqual(merged["capture_regions"][0]["name"], "HUD")
        self.assertEqual(merged["capture_region"], {"left": 10, "top": 20, "width": 300, "height": 80})
        self.assertTrue(merged["obs_mode"])
        self.assertFalse(merged["capture_regions"][0]["ocr"])


if __name__ == "__main__":
    unittest.main()
