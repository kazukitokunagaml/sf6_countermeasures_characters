from __future__ import annotations

import ctypes
import json
import sys
import threading
from typing import Any

from app import (
    CONFIG_PATH,
    MATCHUPS_DIR,
    STATE_PATH,
    MatchupNote,
    load_config,
    parse_matchup_notes,
    watch_match,
)

def run_desktop_overlay() -> None:
    try:
        from PySide6.QtCore import QTimer, Qt
        from PySide6.QtGui import QFont
        from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget
    except ImportError as exc:
        raise SystemExit(
            "PySide6 が必要です。Windows 向けには requirements-windows.txt をインストールしてください。"
        ) from exc

    class OverlayWindow(QWidget):
        def __init__(self, config: dict[str, Any]) -> None:
            super().__init__()
            self.config = config
            self.click_through = bool(config.get("overlay_click_through", False))
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnTopHint
            )
            geometry = config.get(
                "overlay_window",
                {"x": 40, "y": 40, "width": 540, "height": 360},
            )
            self.setGeometry(
                geometry["x"],
                geometry["y"],
                geometry["width"],
                geometry["height"],
            )

            self.container = QWidget(self)
            self.container.setObjectName("container")
            layout = QVBoxLayout(self.container)
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(10)

            self.title = QLabel("SF6 Matchup Overlay")
            self.title.setFont(QFont("Yu Gothic UI", 10))
            self.title.setStyleSheet("color: #AAB6C8; letter-spacing: 2px;")
            layout.addWidget(self.title)

            self.self_label = QLabel("自キャラ: -")
            self.self_label.setFont(QFont("Yu Gothic UI", 16, QFont.Weight.Bold))
            self.self_label.setStyleSheet("color: #F3F6FB;")
            layout.addWidget(self.self_label)

            self.opponent_label = QLabel("相手: 認識待ち")
            self.opponent_label.setFont(QFont("Bahnschrift", 28, QFont.Weight.Bold))
            self.opponent_label.setStyleSheet("color: #FFD166;")
            layout.addWidget(self.opponent_label)

            self.status_label = QLabel("")
            self.status_label.setWordWrap(True)
            self.status_label.setFont(QFont("Yu Gothic UI", 11))
            self.status_label.setStyleSheet("color: #AAB6C8;")
            layout.addWidget(self.status_label)

            self.debug_label = QLabel("")
            self.debug_label.setWordWrap(True)
            self.debug_label.setFont(QFont("Consolas", 10))
            self.debug_label.setStyleSheet("color: #8FA7C7;")
            layout.addWidget(self.debug_label)

            self.notes_label = QLabel("")
            self.notes_label.setWordWrap(True)
            self.notes_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            self.notes_label.setFont(QFont("Yu Gothic UI", 14))
            self.notes_label.setStyleSheet("color: #F3F6FB;")
            layout.addWidget(self.notes_label, stretch=1)

            self.setStyleSheet(
                """
                QWidget#container {
                    background-color: rgba(10, 12, 16, 215);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 20px;
                }
                """
            )

            root_layout = QVBoxLayout(self)
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.addWidget(self.container)

            self.timer = QTimer(self)
            self.timer.timeout.connect(self.refresh_state)
            self.timer.start(350)
            self.refresh_state()

        def showEvent(self, event) -> None:  # type: ignore[override]
            super().showEvent(event)
            self.apply_no_activate_style()

        def apply_no_activate_style(self) -> None:
            if sys.platform != "win32":
                return

            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_TOPMOST = 0x00000008
            WS_EX_TRANSPARENT = 0x00000020
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            HWND_TOPMOST = -1

            user32 = ctypes.windll.user32
            current = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            updated = current | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
            if self.click_through:
                updated |= WS_EX_TRANSPARENT
            else:
                updated &= ~WS_EX_TRANSPARENT
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, updated)
            user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )

        def keyPressEvent(self, event) -> None:  # type: ignore[override]
            if event.key() == Qt.Key.Key_F8:
                self.click_through = not self.click_through
                self.config["overlay_click_through"] = self.click_through
                CONFIG_PATH.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding="utf-8")
                self.apply_no_activate_style()
                self.refresh_state()
                return
            super().keyPressEvent(event)

        def refresh_state(self) -> None:
            if not STATE_PATH.exists():
                return
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            self.self_label.setText(f"自キャラ: {state.get('self_character') or '-'}")
            phase = state.get("phase") or "-"
            self.opponent_label.setText(f"相手: {state.get('opponent') or '認識待ち'}")
            self.status_label.setText(state.get("status") or "")
            confidence = state.get("confidence", 0.0)
            self.debug_label.setText(
                f"phase={phase} confidence={confidence:.3f} click_through={'on' if self.click_through else 'off'} F8 toggle"
            )

            notes = state.get("notes") or []
            lines = [f"・{note}" for note in notes]
            self.notes_label.setText("\n".join(lines))

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    config = load_config(CONFIG_PATH)
    notes: dict[str, MatchupNote] = parse_matchup_notes(MATCHUPS_DIR)
    watcher = threading.Thread(target=watch_match, args=(config, notes), daemon=True)
    watcher.start()

    window = OverlayWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_desktop_overlay()
