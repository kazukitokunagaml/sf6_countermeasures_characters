from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import cv2
import mss
import numpy as np
from PIL import Image, ImageGrab
from mss.exception import ScreenShotError


ROOT = Path(__file__).resolve().parent
DOC_PATH = ROOT / "対策.md"
STATE_PATH = ROOT / "runtime_state.json"
CONFIG_PATH = ROOT / "config.json"
TEMPLATE_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"


CHARACTER_ALIASES = {
    "Luke": "ルーク",
    "Jamie": "ジェイミー",
    "Manon": "マノン",
    "Kimberly": "キンバリー",
    "Marisa": "マリーザ",
    "Lily": "リリー",
    "Juri": "ジュリ",
    "Dee Jay": "ディージェイ",
    "Cammy": "キャミィ",
    "Ryu": "リュウ",
    "E. Honda": "エドモンド本田",
    "Blanka": "ブランカ",
    "Guile": "ガイル",
    "Ken": "ケン",
    "Chun-Li": "春麗",
    "Zangief": "ザンギエフ",
    "Dhalsim": "ダルシム",
    "Rashid": "ラシード",
    "Ed": "エド",
    "Gouki": "豪鬼",
    "M. Bison": "ベガ",
    "Terry": "テリー",
    "Mai": "不知火舞",
    "Elena": "エレナ",
    "Sagat": "サガット",
    "C. Viper": "クリムゾン・ヴァイパー",
    "A.K.I.": "AKI",
}


@dataclass
class MatchupNote:
    opponent: str
    bullets: list[str]


def parse_matchup_notes(path: Path) -> dict[str, MatchupNote]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r"^\d+\.\s+(.+?)(?:\s+\((.+?)\))?\n(.*?)(?=^\d+\.\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    notes: dict[str, MatchupNote] = {}
    for title, english_name, body in pattern.findall(text):
        opponent = normalize_character_name(title.strip())
        entries = []
        for raw_line in body.splitlines():
            line = raw_line.strip()
            if not line or line == "。":
                continue
            line = line.replace("**", "")
            line = re.sub(r"\s+", " ", line)
            entries.append(line)
        if english_name:
            notes[normalize_character_name(english_name)] = MatchupNote(opponent=opponent, bullets=entries)
        notes[opponent] = MatchupNote(opponent=opponent, bullets=entries)
    return notes


def normalize_character_name(name: str) -> str:
    key = name.strip()
    if key in CHARACTER_ALIASES:
        return CHARACTER_ALIASES[key]
    reverse_aliases = {v: v for v in CHARACTER_ALIASES.values()}
    if key in reverse_aliases:
        return reverse_aliases[key]
    return key


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        default = {
            "self_character": "未設定",
            "capture_region": {
                "left": 1320,
                "top": 40,
                "width": 520,
                "height": 180,
            },
            "poll_seconds": 0.75,
            "min_confidence": 0.72,
            "web_port": 8765,
            "capture_backend": "auto",
        }
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default
    config = json.loads(path.read_text(encoding="utf-8"))
    if "capture_backend" not in config:
        config["capture_backend"] = "auto"
        path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def is_wsl() -> bool:
    return sys.platform.startswith("linux") and "microsoft" in platform.release().lower()


def resolve_capture_backend(config: dict[str, Any]) -> str:
    backend = str(config.get("capture_backend", "auto")).lower()
    if backend != "auto":
        return backend
    if is_wsl():
        return "powershell"
    return "mss"


def capture_region_with_mss(region: dict[str, int]) -> Image.Image:
    with mss.mss() as sct:
        shot = sct.grab(region)
        return Image.frombytes("RGB", shot.size, shot.rgb)


def capture_region_with_powershell(region: dict[str, int]) -> Image.Image:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        windows_path = subprocess.run(
            ["wslpath", "-w", str(temp_path)],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        escaped_windows_path = windows_path.replace("'", "''")
        script = """
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$left = [int]{left}
$top = [int]{top}
$width = [int]{width}
$height = [int]{height}
$path = '{path}'
$bmp = New-Object System.Drawing.Bitmap $width, $height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($left, $top, 0, 0, $bmp.Size)
$bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()
""".format(
            left=region["left"],
            top=region["top"],
            width=region["width"],
            height=region["height"],
            path=escaped_windows_path,
        )
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                script,
            ],
            check=True,
            capture_output=True,
        )
        with Image.open(temp_path) as image:
            return image.convert("RGB").copy()
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("cp932", errors="ignore").strip()
        detail = f" {stderr}" if stderr else ""
        raise RuntimeError(f"PowerShell 経由の画面キャプチャに失敗しました。{detail}".strip()) from exc
    finally:
        temp_path.unlink(missing_ok=True)


def capture_region(region: dict[str, int], config: dict[str, Any] | None = None) -> Image.Image:
    backend = resolve_capture_backend(config or load_config(CONFIG_PATH))
    try:
        if backend == "powershell":
            return capture_region_with_powershell(region)
        if backend == "mss":
            return capture_region_with_mss(region)
        raise RuntimeError(f"未対応の capture_backend です: {backend}")
    except (RuntimeError, ScreenShotError, OSError, ValueError):
        bbox = (
            region["left"],
            region["top"],
            region["left"] + region["width"],
            region["top"] + region["height"],
        )
        try:
            return ImageGrab.grab(bbox=bbox)
        except Exception as exc:
            extra = ""
            if is_wsl():
                extra = " WSL では `capture_backend` を `powershell` にすると改善する場合があります。"
            raise RuntimeError(
                "画面キャプチャに失敗しました。GUIセッション上で実行し、capture_region を見直してください。"
                + extra
            ) from exc


def prepare_image(image: Image.Image) -> np.ndarray:
    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    grayscale = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    normalized = cv2.equalizeHist(grayscale)
    return normalized


def match_template(frame: np.ndarray, template: np.ndarray) -> float:
    if frame.shape[0] < template.shape[0] or frame.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    return float(result.max())


def load_templates(template_dir: Path) -> dict[str, list[np.ndarray]]:
    templates: dict[str, list[np.ndarray]] = {}
    if not template_dir.exists():
        template_dir.mkdir(parents=True, exist_ok=True)
        return templates
    for char_dir in sorted(template_dir.iterdir()):
        if not char_dir.is_dir():
            continue
        images: list[np.ndarray] = []
        for file in sorted(char_dir.glob("*.png")):
            images.append(prepare_image(Image.open(file)))
        if images:
            templates[normalize_character_name(char_dir.name)] = images
    return templates


def detect_character(image: Image.Image, templates: dict[str, list[np.ndarray]]) -> tuple[str | None, float]:
    prepared = prepare_image(image)
    best_name = None
    best_score = 0.0
    for name, candidates in templates.items():
        for template in candidates:
            score = match_template(prepared, template)
            if score > best_score:
                best_name = name
                best_score = score
    return best_name, best_score


def write_state(payload: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


class OverlayHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/", "/index.html"):
            body = (STATIC_DIR / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/state":
            body = STATE_PATH.read_bytes() if STATE_PATH.exists() else b"{}"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path.startswith("/static/"):
            target = STATIC_DIR / self.path.removeprefix("/static/")
            if target.exists():
                content_type = "text/plain; charset=utf-8"
                if target.suffix == ".css":
                    content_type = "text/css; charset=utf-8"
                elif target.suffix == ".js":
                    content_type = "application/javascript; charset=utf-8"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), OverlayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def watch_match(config: dict[str, Any], notes: dict[str, MatchupNote]) -> None:
    templates = load_templates(TEMPLATE_DIR)
    write_state(
        {
            "self_character": config["self_character"],
            "opponent": None,
            "confidence": 0.0,
            "capture_region": config["capture_region"],
            "notes": [],
            "status": "テンプレート画像を読み込みました。対戦画面を待機中です。",
            "updated_at": time.time(),
        }
    )
    last_opponent = None
    while True:
        templates = load_templates(TEMPLATE_DIR)
        try:
            screenshot = capture_region(config["capture_region"], config)
        except RuntimeError as exc:
            write_state(
                {
                    "self_character": config["self_character"],
                    "opponent": None,
                    "confidence": 0.0,
                    "capture_region": config["capture_region"],
                    "notes": [],
                    "status": str(exc),
                    "updated_at": time.time(),
                }
            )
            time.sleep(max(config["poll_seconds"], 1.5))
            continue
        opponent, confidence = detect_character(screenshot, templates)
        if not opponent or confidence < config["min_confidence"]:
            payload = {
                "self_character": config["self_character"],
                "opponent": None,
                "confidence": round(confidence, 3),
                "capture_region": config["capture_region"],
                "notes": [],
                "status": "キャラ判定待ち。templates/<キャラ名>/ に比較画像を置いてください。",
                "updated_at": time.time(),
            }
        else:
            matchup = notes.get(opponent)
            payload = {
                "self_character": config["self_character"],
                "opponent": opponent,
                "confidence": round(confidence, 3),
                "capture_region": config["capture_region"],
                "notes": matchup.bullets if matchup else [],
                "status": "相手キャラを認識しました。",
                "updated_at": time.time(),
            }
        if payload["opponent"] != last_opponent:
            write_state(payload)
            last_opponent = payload["opponent"]
        else:
            write_state(payload)
        time.sleep(config["poll_seconds"])


def save_template(character: str, config: dict[str, Any], output_name: str | None) -> Path:
    region = config["capture_region"]
    image = capture_region(region, config)
    character_name = normalize_character_name(character)
    destination_dir = TEMPLATE_DIR / character_name
    destination_dir.mkdir(parents=True, exist_ok=True)
    filename = output_name or f"template_{int(time.time())}.png"
    if not filename.endswith(".png"):
        filename += ".png"
    destination = destination_dir / filename
    image.save(destination)
    return destination


def save_region_preview(image_path: str, config: dict[str, Any], output_name: str | None) -> Path:
    source = Image.open(image_path)
    region = config["capture_region"]
    cropped = source.crop(
        (
            region["left"],
            region["top"],
            region["left"] + region["width"],
            region["top"] + region["height"],
        )
    )
    destination = ROOT / (output_name or "debug_capture_preview.png")
    cropped.save(destination)
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SF6 matchup overlay")
    subparsers = parser.add_subparsers(dest="command")

    watch_parser = subparsers.add_parser("watch", help="Start overlay server and screen watcher")
    watch_parser.add_argument("--port", type=int, default=None)

    capture_parser = subparsers.add_parser("capture-template", help="Capture current region as a character template")
    capture_parser.add_argument("character")
    capture_parser.add_argument("--name", default=None)

    preview_parser = subparsers.add_parser("preview-region", help="Crop capture_region from a local image")
    preview_parser.add_argument("image_path")
    preview_parser.add_argument("--output", default=None)

    subparsers.add_parser("desktop-overlay", help="Start Windows desktop overlay window")
    subparsers.add_parser("show-notes", help="Print parsed matchup notes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(CONFIG_PATH)
    notes = parse_matchup_notes(DOC_PATH)

    if args.command == "capture-template":
        path = save_template(args.character, config, args.name)
        print(f"saved: {path}")
        return

    if args.command == "show-notes":
        print(json.dumps({k: v.bullets for k, v in notes.items()}, ensure_ascii=False, indent=2))
        return

    if args.command == "preview-region":
        path = save_region_preview(args.image_path, config, args.output)
        print(f"saved: {path}")
        return

    if args.command == "desktop-overlay":
        if sys.platform != "win32":
            raise SystemExit("desktop-overlay は Windows ネイティブ実行専用です。WSL では `python app.py watch` を使ってください。")
        from desktop_overlay import run_desktop_overlay

        run_desktop_overlay()
        return

    port = args.port or config["web_port"]
    server = run_server(port)
    print(f"overlay: http://127.0.0.1:{port}")
    try:
        watch_match(config, notes)
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
