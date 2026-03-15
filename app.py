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
from difflib import SequenceMatcher
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

import cv2
import mss
import numpy as np
from PIL import Image, ImageGrab
from mss.exception import ScreenShotError

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional dependency
    pytesseract = None


ROOT = Path(__file__).resolve().parent
MATCHUPS_DIR = ROOT / "matchups"
STATE_PATH = ROOT / "runtime_state.json"
CONFIG_PATH = ROOT / "config.json"
TEMPLATE_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"
DEBUG_DIR = ROOT / "debug"


CHARACTER_ALIASES = {
    "LUKE": "LUKE",
    "Luke": "LUKE",
    "ルーク": "LUKE",
    "JAMIE": "JAMIE",
    "Jamie": "JAMIE",
    "ジェイミー": "JAMIE",
    "MANON": "MANON",
    "Manon": "MANON",
    "マノン": "MANON",
    "KIMBERLY": "KIMBERLY",
    "Kimberly": "KIMBERLY",
    "キンバリー": "KIMBERLY",
    "MARISA": "MARISA",
    "Marisa": "MARISA",
    "マリーザ": "MARISA",
    "LILY": "LILY",
    "Lily": "LILY",
    "リリー": "LILY",
    "JP": "JP",
    "JURI": "JURI",
    "Juri": "JURI",
    "ジュリ": "JURI",
    "DEE JAY": "DEE JAY",
    "Dee Jay": "DEE JAY",
    "ディージェイ": "DEE JAY",
    "CAMMY": "CAMMY",
    "Cammy": "CAMMY",
    "キャミィ": "CAMMY",
    "RYU": "RYU",
    "Ryu": "RYU",
    "リュウ": "RYU",
    "E. HONDA": "E. HONDA",
    "E. Honda": "E. HONDA",
    "エドモンド本田": "E. HONDA",
    "BLANKA": "BLANKA",
    "Blanka": "BLANKA",
    "ブランカ": "BLANKA",
    "GUILE": "GUILE",
    "Guile": "GUILE",
    "ガイル": "GUILE",
    "KEN": "KEN",
    "Ken": "KEN",
    "ケン": "KEN",
    "CHUN-LI": "CHUN-LI",
    "Chun-Li": "CHUN-LI",
    "春麗": "CHUN-LI",
    "ZANGIEF": "ZANGIEF",
    "Zangief": "ZANGIEF",
    "ザンギエフ": "ZANGIEF",
    "DHALSIM": "DHALSIM",
    "Dhalsim": "DHALSIM",
    "ダルシム": "DHALSIM",
    "RASHID": "RASHID",
    "Rashid": "RASHID",
    "ラシード": "RASHID",
    "A.K.I.": "A.K.I.",
    "A.K.I": "A.K.I.",
    "AKI": "A.K.I.",
    "アキ": "A.K.I.",
    "ED": "ED",
    "Ed": "ED",
    "エド": "ED",
    "AKUMA": "AKUMA",
    "Gouki": "AKUMA",
    "豪鬼": "AKUMA",
    "M. BISON": "M. BISON",
    "M. Bison": "M. BISON",
    "ベガ": "M. BISON",
    "TERRY": "TERRY",
    "Terry": "TERRY",
    "テリー": "TERRY",
    "MAI": "MAI",
    "Mai": "MAI",
    "不知火舞": "MAI",
    "ELENA": "ELENA",
    "Elena": "ELENA",
    "エレナ": "ELENA",
    "SAGAT": "SAGAT",
    "Sagat": "SAGAT",
    "サガット": "SAGAT",
    "C. VIPER": "C. VIPER",
    "C. Viper": "C. VIPER",
    "クリムゾン・ヴァイパー": "C. VIPER",
}


@dataclass
class MatchupNote:
    opponent: str
    bullets: list[str]


@dataclass
class CandidateScore:
    name: str
    template_score: float
    ocr_score: float
    combined_score: float


def parse_matchup_notes(path: Path) -> dict[str, MatchupNote]:
    notes: dict[str, MatchupNote] = {}
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        return notes
    for file in sorted(path.glob("*.md")):
        opponent = normalize_character_name(file.stem)
        entries = []
        for raw_line in file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            line = line.replace("**", "")
            line = re.sub(r"\s+", " ", line)
            entries.append(line)
        notes[opponent] = MatchupNote(opponent=opponent, bullets=entries)
    return notes


def normalize_character_name(name: str) -> str:
    key = name.strip()
    if key in CHARACTER_ALIASES:
        return CHARACTER_ALIASES[key]
    upper_key = key.upper()
    if upper_key in CHARACTER_ALIASES:
        return CHARACTER_ALIASES[upper_key]
    return key


def default_capture_region() -> dict[str, int]:
    return {"left": 1320, "top": 40, "width": 520, "height": 180}


def sanitize_region(region: dict[str, Any]) -> dict[str, int]:
    return {
        "left": max(0, int(region["left"])),
        "top": max(0, int(region["top"])),
        "width": max(1, int(region["width"])),
        "height": max(1, int(region["height"])),
    }


def default_capture_regions(base_region: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    region = sanitize_region(base_region or default_capture_region())
    return [
        {
            "name": "VERSUS",
            **region,
            "enabled": True,
            "ocr": True,
        }
    ]


def migrate_config(config: dict[str, Any]) -> dict[str, Any]:
    changed = False
    if "capture_backend" not in config:
        config["capture_backend"] = "auto"
        changed = True
    if "capture_region" not in config:
        config["capture_region"] = default_capture_region()
        changed = True
    config["capture_region"] = sanitize_region(config["capture_region"])
    if "capture_regions" not in config:
        config["capture_regions"] = default_capture_regions(config["capture_region"])
        changed = True
    else:
        normalized_regions = []
        for index, region in enumerate(config["capture_regions"], start=1):
            normalized_regions.append(
                {
                    "name": str(region.get("name") or f"PHASE {index}").upper(),
                    **sanitize_region(region),
                    "enabled": bool(region.get("enabled", True)),
                    "ocr": bool(region.get("ocr", True)),
                }
            )
        config["capture_regions"] = normalized_regions
    if "ocr_enabled" not in config:
        config["ocr_enabled"] = True
        changed = True
    if "ocr_weight" not in config:
        config["ocr_weight"] = 0.35
        changed = True
    if "debug_save_images" not in config:
        config["debug_save_images"] = True
        changed = True
    if "obs_mode" not in config:
        config["obs_mode"] = False
        changed = True
    if "overlay_click_through" not in config:
        config["overlay_click_through"] = False
        changed = True
    if "overlay_window" not in config:
        config["overlay_window"] = {"x": 40, "y": 40, "width": 540, "height": 360}
        changed = True
    return config if changed else config


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        default = {
            "self_character": "未設定",
            "capture_region": default_capture_region(),
            "capture_regions": default_capture_regions(),
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
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        return default
    config = migrate_config(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    return config


def save_config(config: dict[str, Any]) -> None:
    normalized = migrate_config(config)
    CONFIG_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


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
            ["powershell.exe", "-NoProfile", "-Command", script],
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
        except Exception as exc:  # pragma: no cover - GUI dependent
            extra = ""
            if is_wsl():
                extra = " WSL では `capture_backend` を `powershell` にすると改善する場合があります。"
            raise RuntimeError(
                "画面キャプチャに失敗しました。GUIセッション上で実行し、capture_region を見直してください。" + extra
            ) from exc


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def prepare_template_variants(image: Image.Image) -> list[np.ndarray]:
    return build_variants(pil_to_bgr(image))


def build_variants(bgr: np.ndarray) -> list[np.ndarray]:
    grayscale = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    equalized = cv2.equalizeHist(grayscale)
    blur = cv2.GaussianBlur(equalized, (3, 3), 0)
    _, binary = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(blur, 80, 160)
    return [equalized, binary, edges]


def prepare_ocr_image(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    enlarged = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    normalized = cv2.equalizeHist(enlarged)
    _, binary = cv2.threshold(normalized, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def resize_image(image: np.ndarray, scale: float) -> np.ndarray:
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)


def match_template(frame: np.ndarray, template: np.ndarray) -> float:
    if frame.shape[0] < template.shape[0] or frame.shape[1] < template.shape[1]:
        return 0.0
    result = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
    return float(result.max())


def load_templates(template_dir: Path) -> dict[str, list[list[np.ndarray]]]:
    templates: dict[str, list[list[np.ndarray]]] = {}
    template_dir.mkdir(parents=True, exist_ok=True)
    for char_dir in sorted(template_dir.iterdir()):
        if not char_dir.is_dir():
            continue
        images: list[list[np.ndarray]] = []
        for file in sorted(char_dir.glob("*.png")):
            with Image.open(file) as image:
                images.append(prepare_template_variants(image))
        if images:
            templates[normalize_character_name(char_dir.name)] = images
    return templates


def canonical_candidates(notes: dict[str, MatchupNote], templates: dict[str, list[list[np.ndarray]]]) -> list[str]:
    return sorted(set(notes) | set(templates))


def normalize_ocr_text(text: str) -> str:
    return re.sub(r"[^A-Z0-9.\- ]+", "", text.upper())


def run_ocr(image: Image.Image, candidates: list[str], enabled: bool) -> dict[str, Any]:
    if not enabled:
        return {"available": False, "reason": "ocr disabled", "text": "", "matches": {}}
    if pytesseract is None:
        return {"available": False, "reason": "pytesseract not installed", "text": "", "matches": {}}
    try:
        ocr_image = prepare_ocr_image(pil_to_bgr(image))
        text = pytesseract.image_to_string(Image.fromarray(ocr_image), config="--psm 7").strip()
    except Exception as exc:  # pragma: no cover - external binary dependent
        return {"available": False, "reason": str(exc), "text": "", "matches": {}}
    normalized = normalize_ocr_text(text)
    matches: dict[str, float] = {}
    if normalized:
        for candidate in candidates:
            score = SequenceMatcher(None, normalized, normalize_ocr_text(candidate)).ratio()
            if normalize_ocr_text(candidate) in normalized:
                score = max(score, 0.98)
            if score >= 0.45:
                matches[candidate] = round(score, 3)
    return {"available": True, "text": normalized, "raw_text": text, "matches": matches}


def detect_character(
    image: Image.Image,
    templates: dict[str, list[list[np.ndarray]]],
    candidates: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    bgr = pil_to_bgr(image)
    frame_variants = build_variants(bgr)
    frame_scales = [0.92, 1.0, 1.08]
    template_scores: dict[str, float] = {candidate: 0.0 for candidate in candidates}

    for name, candidate_templates in templates.items():
        best_score = 0.0
        for template_variants in candidate_templates:
            for frame_variant, template_variant in zip(frame_variants, template_variants):
                for scale in frame_scales:
                    scaled_template = resize_image(template_variant, scale)
                    best_score = max(best_score, match_template(frame_variant, scaled_template))
        template_scores[name] = round(best_score, 3)

    ocr_result = run_ocr(image, candidates, bool(config.get("ocr_enabled", True)))
    ocr_matches = ocr_result.get("matches", {})
    ocr_weight = float(config.get("ocr_weight", 0.35))
    candidate_scores: list[CandidateScore] = []
    for candidate in candidates:
        template_score = template_scores.get(candidate, 0.0)
        ocr_score = float(ocr_matches.get(candidate, 0.0))
        combined = max(template_score, min(1.0, template_score * (1.0 - ocr_weight) + ocr_score * ocr_weight))
        candidate_scores.append(
            CandidateScore(
                name=candidate,
                template_score=round(template_score, 3),
                ocr_score=round(ocr_score, 3),
                combined_score=round(combined, 3),
            )
        )
    candidate_scores.sort(key=lambda item: item.combined_score, reverse=True)
    best = candidate_scores[0] if candidate_scores else CandidateScore("", 0.0, 0.0, 0.0)
    return {
        "opponent": best.name or None,
        "confidence": best.combined_score,
        "top_candidates": [
            {
                "name": item.name,
                "template_score": item.template_score,
                "ocr_score": item.ocr_score,
                "combined_score": item.combined_score,
            }
            for item in candidate_scores[:5]
        ],
        "ocr": ocr_result,
        "preprocessed": frame_variants[0],
    }


def ensure_debug_dir() -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)


def write_debug_assets(image: Image.Image, preprocessed: np.ndarray | None) -> dict[str, str]:
    ensure_debug_dir()
    capture_path = DEBUG_DIR / "last_capture.png"
    image.save(capture_path)
    result = {"capture": "/debug/last_capture.png"}
    if preprocessed is not None:
        preprocessed_path = DEBUG_DIR / "last_preprocessed.png"
        Image.fromarray(preprocessed).save(preprocessed_path)
        result["preprocessed"] = "/debug/last_preprocessed.png"
    return result


def write_state(payload: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def current_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def list_templates(template_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if not template_dir.exists():
        return entries
    for char_dir in sorted(template_dir.iterdir()):
        if not char_dir.is_dir():
            continue
        character = normalize_character_name(char_dir.name)
        files = []
        for file in sorted(char_dir.glob("*.png")):
            stat = file.stat()
            files.append(
                {
                    "name": file.name,
                    "size": stat.st_size,
                    "updated_at": stat.st_mtime,
                    "delete_url": f"/templates?character={quote(character)}&file={quote(file.name)}",
                }
            )
        if files:
            entries.append({"character": character, "count": len(files), "files": files})
    return entries


def delete_template_file(template_dir: Path, character: str, filename: str) -> bool:
    character_name = normalize_character_name(character)
    target = (template_dir / character_name / Path(filename).name).resolve()
    try:
        target.relative_to(template_dir.resolve())
    except ValueError as exc:
        raise RuntimeError("不正なテンプレートパスです。") from exc
    if not target.exists() or target.suffix.lower() != ".png":
        return False
    target.unlink()
    parent = target.parent
    if parent != template_dir.resolve() and not any(parent.iterdir()):
        parent.rmdir()
    return True


def patch_config(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    for key, value in patch.items():
        if key == "capture_region" and isinstance(value, dict):
            merged[key] = sanitize_region(value)
        elif key == "capture_regions" and isinstance(value, list):
            regions = []
            for index, region in enumerate(value, start=1):
                regions.append(
                    {
                        "name": str(region.get("name") or f"PHASE {index}").upper(),
                        **sanitize_region(region),
                        "enabled": bool(region.get("enabled", True)),
                        "ocr": bool(region.get("ocr", True)),
                    }
                )
            merged[key] = regions
        elif key == "overlay_window" and isinstance(value, dict):
            merged[key] = {
                "x": int(value.get("x", current.get("overlay_window", {}).get("x", 40))),
                "y": int(value.get("y", current.get("overlay_window", {}).get("y", 40))),
                "width": max(1, int(value.get("width", current.get("overlay_window", {}).get("width", 540)))),
                "height": max(1, int(value.get("height", current.get("overlay_window", {}).get("height", 360)))),
            }
        else:
            merged[key] = value
    if "capture_regions" in merged and merged["capture_regions"]:
        merged["capture_region"] = sanitize_region(merged["capture_regions"][0])
    elif "capture_region" in merged:
        merged["capture_regions"] = default_capture_regions(merged["capture_region"])
    return migrate_config(merged)


class OverlayHandler(BaseHTTPRequestHandler):
    def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            body = (STATIC_DIR / "index.html").read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/state":
            self.send_json(current_state())
            return
        if parsed.path == "/templates":
            self.send_json({"templates": list_templates(TEMPLATE_DIR)})
            return
        if parsed.path == "/config":
            self.send_json(load_config(CONFIG_PATH))
            return
        if parsed.path.startswith("/static/"):
            target = STATIC_DIR / parsed.path.removeprefix("/static/")
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
        if parsed.path.startswith("/debug/"):
            target = DEBUG_DIR / parsed.path.removeprefix("/debug/")
            if target.exists():
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(target.read_bytes())
                return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/config":
            current = load_config(CONFIG_PATH)
            updated = patch_config(current, self.read_json_body())
            save_config(updated)
            self.send_json(updated)
            return
        if parsed.path == "/preview-capture":
            body = self.read_json_body()
            config = load_config(CONFIG_PATH)
            region = sanitize_region(body.get("region") or config["capture_region"])
            image = capture_region(region, config)
            ensure_debug_dir()
            preview_path = DEBUG_DIR / "preview_capture.png"
            image.save(preview_path)
            self.send_json({"ok": True, "path": "/debug/preview_capture.png", "region": region})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/templates":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        params = parse_qs(parsed.query)
        character = unquote(params.get("character", [""])[0]).strip()
        filename = unquote(params.get("file", [""])[0]).strip()
        if not character or not filename:
            self.send_json({"error": "character と file が必要です。"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            deleted = delete_template_file(TEMPLATE_DIR, character, filename)
        except RuntimeError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        if not deleted:
            self.send_json({"error": "テンプレートが見つかりません。"}, HTTPStatus.NOT_FOUND)
            return
        self.send_json({"ok": True, "templates": list_templates(TEMPLATE_DIR)})

    def log_message(self, format: str, *args: Any) -> None:
        return


def run_server(port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), OverlayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def evaluate_regions(
    config: dict[str, Any],
    notes: dict[str, MatchupNote],
    templates: dict[str, list[list[np.ndarray]]],
) -> dict[str, Any]:
    candidates = canonical_candidates(notes, templates)
    regions = [region for region in config.get("capture_regions", []) if region.get("enabled", True)]
    if not regions:
        regions = default_capture_regions(config.get("capture_region"))

    best_result: dict[str, Any] | None = None
    best_image: Image.Image | None = None
    region_debug = []

    for region in regions:
        capture = capture_region(sanitize_region(region), config)
        detection = detect_character(capture, templates, candidates, config)
        detection["phase"] = region["name"]
        detection["capture_region"] = sanitize_region(region)
        region_debug.append(
            {
                "phase": region["name"],
                "capture_region": sanitize_region(region),
                "confidence": detection["confidence"],
                "top_candidates": detection["top_candidates"][:3],
                "ocr_text": detection["ocr"].get("text", ""),
            }
        )
        if best_result is None or detection["confidence"] > best_result["confidence"]:
            best_result = detection
            best_image = capture

    assert best_result is not None and best_image is not None
    best_result["region_debug"] = region_debug
    best_result["image"] = best_image
    return best_result


def watch_match(config: dict[str, Any], notes: dict[str, MatchupNote]) -> None:
    write_state(
        {
            "self_character": config["self_character"],
            "opponent": None,
            "confidence": 0.0,
            "capture_region": config["capture_region"],
            "phase": None,
            "notes": [],
            "status": "テンプレート画像を読み込みました。対戦画面を待機中です。",
            "updated_at": time.time(),
        }
    )
    while True:
        config = load_config(CONFIG_PATH)
        templates = load_templates(TEMPLATE_DIR)
        try:
            detection = evaluate_regions(config, notes, templates)
        except RuntimeError as exc:
            write_state(
                {
                    "self_character": config["self_character"],
                    "opponent": None,
                    "confidence": 0.0,
                    "capture_region": config["capture_region"],
                    "phase": None,
                    "notes": [],
                    "status": str(exc),
                    "updated_at": time.time(),
                    "debug": {"capture_backend": resolve_capture_backend(config)},
                }
            )
            time.sleep(max(float(config["poll_seconds"]), 1.5))
            continue

        opponent = detection["opponent"]
        confidence = float(detection["confidence"])
        debug_assets = {}
        if config.get("debug_save_images", True):
            debug_assets = write_debug_assets(detection["image"], detection.get("preprocessed"))
        if not opponent or confidence < float(config["min_confidence"]):
            payload = {
                "self_character": config["self_character"],
                "opponent": None,
                "confidence": round(confidence, 3),
                "capture_region": detection["capture_region"],
                "phase": detection["phase"],
                "notes": [],
                "status": "キャラ判定待ち。templates/<公式キャラ名>/ に比較画像を置くか、OCR を確認する。",
                "updated_at": time.time(),
            }
        else:
            matchup = notes.get(opponent)
            payload = {
                "self_character": config["self_character"],
                "opponent": opponent,
                "confidence": round(confidence, 3),
                "capture_region": detection["capture_region"],
                "phase": detection["phase"],
                "notes": matchup.bullets if matchup else [],
                "status": f"相手キャラを認識した。phase={detection['phase']}",
                "updated_at": time.time(),
            }
        payload["debug"] = {
            "capture_backend": resolve_capture_backend(config),
            "ocr": detection["ocr"],
            "top_candidates": detection["top_candidates"],
            "regions": detection["region_debug"],
            "images": debug_assets,
            "template_count": sum(len(items) for items in templates.values()),
        }
        write_state(payload)
        time.sleep(float(config["poll_seconds"]))


def save_template(character: str, config: dict[str, Any], output_name: str | None) -> Path:
    image = capture_region(config["capture_region"], config)
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
    notes = parse_matchup_notes(MATCHUPS_DIR)
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
