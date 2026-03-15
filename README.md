# SF6 Matchup Overlay

`matchups/` 配下のキャラ別 Markdown を読み込み、画面の一部をキャプチャして相手キャラ名領域を認識し、対策をブラウザやデスクトップオーバーレイに表示するツールです。

Windows ではブラウザ版に加えて、非アクティブ表示のデスクトップオーバーレイも使えます。WSL ではブラウザ版を使います。

## できること

- `matchups/<公式キャラ名>.md` から相手キャラごとの対策を抽出
- 指定領域を定期キャプチャ
- `templates/<公式キャラ名>/*.png` の画像をテンプレートマッチで照合
- OCR を併用して文字認識も参照
- フェーズごとに複数の認識領域を切り替え
- `debug/` に認識時の画像を保存
- `http://127.0.0.1:8765` に対策オーバーレイを表示

## セットアップ

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

OCR を使う場合は別途 Tesseract OCR 本体が必要です。`pytesseract` は Python 側のラッパだけを入れます。

### Tesseract の導入

Windows:

```powershell
winget install UB-Mannheim.TesseractOCR
```

インストール後、`tesseract.exe` に PATH が通っていることを確認する。新しいターミナルで次を実行してバージョンが出ればよい。

```powershell
tesseract --version
```

WSL / Ubuntu:

```bash
sudo apt update
sudo apt install -y tesseract-ocr
tesseract --version
```

Windows 側の画面を WSL から OCR したい場合は、WSL 側にも Tesseract を入れる。

`python3 -m venv` が使える環境なら、通常の `venv` でも構いません。

Windows で `.exe` 化する場合は追加で以下を入れます。

```bash
uv pip install -r requirements.txt -r requirements-windows.txt
```

初回起動で [config.json](/home/sige1/workspace/sf6/config.json) が生成されます。

WSL では既定で `capture_backend: "auto"` から Windows 側の PowerShell キャプチャを選びます。既存の `config.json` を使っている場合も、自動でこの設定が追記されます。

## 最短で試す

WSL2 でまず動作確認したい場合は、次の順で進めるのが最短です。

1. SF6 を起動して、対戦画面かキャラクター選択画面を表示します。
2. WSL 側でこのディレクトリに移動します。
3. 次を実行してオーバーレイを起動します。

```bash
./run_wsl.sh
```

4. 別のブラウザタブで `http://127.0.0.1:8765` を開きます。
5. [config.json](/home/sige1/workspace/sf6/config.json) の `capture_regions` が合っていれば、その領域群を監視し続けます。

初回はテンプレート画像がないので、ブラウザには「キャラ判定待ち」と出ます。次の「使い方」の手順でテンプレート画像を作ってください。

## 使い方

1. `config.json` の `self_character` と `capture_regions` を自分の環境に合わせます。
2. 対戦画面で相手キャラ名の文字列が安定して映る位置を、ブラウザの設定パネルか `capture_regions` で設定します。
3. 各キャラについて比較用テンプレート画像を保存します。

対策文は `matchups/<公式キャラ名>.md` に1キャラ1ファイルで置きます。ファイル名は公式の英語大文字表記に揃えます。例えば `LUKE.md`、`CHUN-LI.md`、`A.K.I.md` です。各行がそのままオーバーレイの項目として表示されます。

```bash
source .venv/bin/activate
python app.py capture-template キャミィ
python app.py capture-template ケン
```

保存先は `templates/<公式キャラ名>/template_<timestamp>.png` です。比較は固定領域前提なので、テンプレート取得時と同じ解像度、同じUIスケールで使ってください。OCR は補助経路なので、まずテンプレートを揃える方が安定します。

追加した [キャラ画面.png](/home/sige1/workspace/sf6/キャラ画面.png) を基準にした暫定値は以下です。

```json
"capture_region": {
  "left": 1540,
  "top": 1180,
  "width": 960,
  "height": 220
}
```

相手側のネームプレートを少し大きめに含めています。確認したいときは次を実行すると、今の `capture_region` で切り出した画像を保存できます。ブラウザの「現在位置を確認」でも同じ確認ができます。

```bash
source .venv/bin/activate
python app.py preview-region キャラ画面.png
```

生成された `debug_capture_preview.png` を見て、相手名やポートレートがしっかり含まれているか確認してください。ズレている場合は [config.json](/home/sige1/workspace/sf6/config.json) の `capture_region` を調整します。

4. 監視を開始します。

```bash
source .venv/bin/activate
python app.py watch
```

WSL では次のスクリプトでも起動できます。

```bash
./run_wsl.sh
```

5. ブラウザで `http://127.0.0.1:8765` を開きます。透過ブラウザやOBSブラウザソースに載せれば対戦中オーバーレイとして使えます。

### WSL での具体例

最初の1キャラだけ登録して確認するなら、例えば次の流れです。

```bash
./run_wsl.sh
```

別ターミナルで:

```bash
source .venv/bin/activate
python app.py capture-template ケン
```

これで `templates/KEN/` に画像が保存されます。保存後は `watch` が自動でテンプレートを再読込するので、プロセスを再起動しなくて構いません。

追加でキャラを増やすときは同じ要領で `capture-template` を繰り返します。

```bash
python app.py capture-template キャミィ
python app.py capture-template ジュリ
python app.py capture-template 豪鬼
```

保存済みテンプレートはブラウザ下部に一覧表示されます。不要になった PNG はその場で削除できます。

## ブラウザ設定パネル

- `capture_regions` を複数登録できる。各 phase ごとに `left/top/width/height` を編集して保存する。
- 「現在位置を確認」でライブキャプチャを `debug/preview_capture.png` に保存する。
- `obs_mode` を ON にすると、設定 UI とデバッグ UI を消した軽量表示になる。
- 認識候補、OCR 結果、保存画像はブラウザのデバッグ欄から確認できる。

## WSL で使う場合

- `watch` と `capture-template` は WSL2 からそのまま実行できます。
- 画面キャプチャは Windows 側の `powershell.exe` を呼び出して行います。
- `desktop-overlay` は Windows ネイティブ実行専用です。WSL ではブラウザ表示を使ってください。
- `./run_wsl.sh` を使うと、`.venv` 作成と依存導入を含めてそのまま `watch` を起動できます。

必要なら `config.json` でキャプチャ方式を明示できます。

```json
"capture_backend": "powershell"
```

指定可能な値は `auto` / `powershell` / `mss` です。WSL では `auto` を推奨します。

### WSL で困ったとき

- `画面キャプチャに失敗しました` と出る場合は、Windows 側で対象画面が表示されているか確認します。
- `capture_region` が合っていないと認識しないので、まず `python app.py preview-region キャラ画面.png` で切り出し位置を確認します。
- 認識率が低い場合は、同じ解像度と UI スケールでテンプレート画像を増やし、OCR 結果と `debug/last_capture.png` を確認します。
- `http://127.0.0.1:8765` が開けない場合は、すでに同じポートが使われていないか確認し、必要なら `./run_wsl.sh --port 8766` のように変えます。

## Windows デスクトップオーバーレイ

ブラウザを使わずに、常時最前面で出すウィンドウ版もあります。

```bash
python app.py desktop-overlay
```

- 枠なし
- 常時最前面
- 表示時にフォーカスを奪わないよう `WS_EX_NOACTIVATE` を付与
- `F8` でクリック透過を切り替え

位置とサイズは `config.json` の `overlay_window` で調整できます。

```json
"overlay_window": {
  "x": 40,
  "y": 40,
  "width": 540,
  "height": 360
}
```

注意点として、この非アクティブ制御は Windows 専用です。Linux や macOS では同じ保証にはしていません。

## EXE 化

Windows で以下を実行すると `dist/sf6_overlay.exe` と `dist/sf6_overlay.zip` を作れます。

```bat
build_windows.bat
```

## テスト

依存を増やさず `unittest` で回帰テストを入れてある。少なくとも次は変更後に回す。

```bash
python -m unittest discover -s tests -v
```

## 調整ポイント

- `capture_regions`: 相手キャラ名やポートレートが含まれる矩形。複数 phase を持てる。
- `min_confidence`: 誤認識が多い場合は上げる
- `poll_seconds`: 更新頻度
- `ocr_weight`: OCR をどれだけ混ぜるか

## 制限

- OCR は Tesseract 本体が無い環境では自動で無効化されます。
- 認識はテンプレートマッチ中心なので、解像度や UI スケールが大きく変わると精度が落ちます。
- キャラ名表示部分を切り出す前提なので、まずは `VERSUS` 画面や対戦開始直後のHUDなど、見た目が安定する場所で使うのが安全です。
- Windows デスクトップオーバーレイは追加済みですが、非アクティブ制御は Windows 専用です。

今後の改善候補は [TODO.md](/home/sige1/workspace/sf6/TODO.md) にまとめています。
