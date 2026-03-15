# TODO

## 未着手

- 実画面で認識精度を検証する。`VERSUS`、対戦中 HUD、解像度差ありの条件で `debug/last_capture.png` と `runtime_state.json` を見ながら `capture_regions`、`min_confidence`、`ocr_weight` を詰める。
- 未対応キャラを検出するチェックを追加する。`matchups/` と `templates/` の不足を一覧で見えるようにする。
  実施フロー:
  1. 公式キャラ名の定数リストを `app.py` か専用モジュールに切り出す。`matchups/*.md` と `templates/*/` の正とする。
  2. `python app.py audit-assets` のようなコマンドを追加する。
  3. コマンド内で `matchups/` のファイル名と `templates/` のディレクトリ名を正規化し、公式キャラ名リストと突き合わせる。
  4. 出力は少なくとも `missing_matchups`、`missing_templates`、`unknown_matchups`、`unknown_templates` の4分類にする。
  5. `missing_templates` は「テンプレート枚数 0 のキャラ」も含める。必要なら枚数も出す。
  6. 結果は CLI の標準出力に JSON と要約の両方を出せる形にする。まずは人間向けテキスト、必要なら `--json` を追加する。
  7. README に「対策ファイルとテンプレートの棚卸し方法」として実行例を追記する。
  8. 回帰テストとして「不足あり」「未知ディレクトリあり」「全部揃っている」の3ケースを `tests/` に追加する。
- OCR の実運用確認をする。Tesseract 本体を入れた環境で、日本語 UI と英語キャラ名の混在時にどこまで効くかを確認する。

## 実装済み

- ブラウザから `capture_regions` を編集して保存できる。
- 認識失敗時のデバッグ情報と画像を `runtime_state.json` と `debug/` に出す。
- OCR を併用した認識経路を追加した。
- 画像前処理とスケール差の吸収を追加した。
- フェーズごとに認識領域を切り替えられる。
- OBS 向けの表示モードを追加した。
- Windows / WSL の起動スクリプトを `scripts/` に整理した。
- デスクトップオーバーレイのクリック透過を `F8` で切り替えられる。
- Windows の EXE ビルドと zip 化を自動化した。
