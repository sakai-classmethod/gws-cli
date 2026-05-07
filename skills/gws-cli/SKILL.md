---
name: gws-cli
description: |
  Google Workspace リソース（Calendar 添付ファイル、Google Docs テキスト、マイドライブへのアップロード、Drive ファイルのダウンロード）を扱う CLI スキル。
  以下の場面で使用する:
  - 会議の文字起こしを取得したいとき（「文字起こし取って」「トランスクリプト取得」「議事録の元データ」）
  - Calendar イベントの添付ファイルを確認したいとき（「添付ファイル一覧」「Meet のドキュメント」）
  - Google Docs の本文をテキストで取得したいとき（「Docs の中身を取得」「ドキュメント読んで」）
  - Meet の会議内容を要約・分析する前段階として元データが必要なとき
  - ローカルファイルをマイドライブにアップロードしたいとき（「Drive に上げて」「PPTX をマイドライブに保存」「生成した PDF をアップロード」）
  - Agent が生成した成果物（提案書・スライド・レポートなど）を Drive へ保存したいとき
  - Drive 上のファイルをローカルにダウンロードしたいとき（「Drive から取ってきて」「PPTX をダウンロード」「Doc を docx で保存」）
allowed-tools:
  - "Bash(gws-cli:*)"
  - "mcp__claude_ai_Google_Calendar__list_events"
  - "mcp__claude_ai_Google_Calendar__get_event"
---

# gws-cli: Google Workspace CLI

Google Workspace のリソースを読み書きする CLI ツール。

- 読み取り: Calendar 添付ファイル / Google Docs テキスト（Meet 文字起こし取得など） / Drive ファイルダウンロード
- 書き込み: ローカルファイルをマイドライブへアップロード（Agent 生成物の保存など）

## 前提条件

- リポジトリ: `github.com/sakai-classmethod/gws-cli`
- ADC 認証済み（`calendar.readonly` + `drive.readonly` + `drive.file` スコープ）
- `uv tool install` 済み（`gws-cli` コマンドが PATH で使用可能）

## コマンド一覧

### Calendar 添付ファイル取得

```bash
gws-cli calendar attachments <event-id> [--calendar-id <calendar-id>]
```

- `event-id`: Google Calendar のイベント ID
- `--calendar-id`: カレンダー ID（デフォルト: `primary`）
- 出力: JSON 配列（`fileId`, `title`, `fileUrl`, `mimeType`）
- 添付なしの場合は `[]` を返す（exit 0）

### Docs テキスト取得

```bash
gws-cli docs get <doc-id> [--format plain|md] [--section transcript|notes]
```

- `doc-id`: Google Docs のドキュメント ID（添付ファイルの `fileId`）
- `--format`: 出力形式（デフォルト: `plain`、`md` で Markdown 変換）
- `--section`: セクション抽出（`transcript` で文字起こしのみ、`notes` でメモのみ）

挙動:
- `--format` と `--section` は独立に適用される（先に format 変換 → 後からセクション抽出）。両方同時に指定可能
- `doc-id` は Google Docs 形式（`mimeType: application/vnd.google-apps.document`）のファイルに限定。PDF / スプレッドシート / スライド等は `files.export` が失敗しエラー終了
- `--section transcript`: `📖 文字起こし` マーカー（含む）から本文末尾までを返す。後続に `📝 メモ` が続く場合もそれを含めて末尾まで返す
- `--section notes`: `📝 メモ` マーカー（含む）から、本文中に `📖 文字起こし` が現れる場合はその直前まで、現れない場合は本文末尾まで返す（Meet ドキュメントはメモ → 文字起こしの順で生成される想定）
- `--section transcript|notes` 指定時、対応するマーカーが本文に含まれない場合は全文を返す（silent fallback。エラーにはならず exit 0 / stderr への警告もなし）。fallback を呼び出し側で検知するには、出力本文の先頭 1 行目に該当マーカー（`📖 文字起こし` / `📝 メモ`）で始まるかを確認する（マーカー自体は出力に含まれる仕様のため、含まれていなければ fallback 発生）

### Drive ダウンロード

```bash
gws-cli drive download <file-id> [<dest>] [--export <format>] [--overwrite]
```

- `file-id`: Drive のファイル ID（必須）
- `dest`: 保存先（省略時はカレントディレクトリ、ディレクトリ指定で配下に Drive 名+拡張子で保存、`-` で stdout）
- `--export`: Google native（Docs/Sheets/Slides/Drawings）のエクスポート形式
  - shortcut: `pdf`, `docx`, `xlsx`, `pptx`, `png`, `jpeg`, `csv`, `txt`, `rtf`, `odt`, `ods`, `epub`, `tsv`
  - MIME 直指定可（例: `--export application/pdf`）
  - 既定: Docs→docx / Sheets→xlsx / Slides→pptx / Drawings→png
- `--overwrite`: 既存ローカルファイルがあれば上書き
- 出力: ファイル保存時は JSON を stdout、`-` の場合は bytes を stdout / JSON を stderr

挙動:

- Google native は `files.export` 経由でエクスポート、それ以外は `files.get_media` で chunked 取得
- 共有ドライブ上のファイルにも対応（読み取りのみ）
- 拒否される mimeType: フォルダ / shortcut / form / site / `audio/*` / `video/*`
- `files.export` の 10MB 出力上限に該当する場合は専用エラーで Drive UI / Takeout を案内
- 書き込みは temp ファイル → atomic replace（途中失敗時に半端ファイルを残さない）

`docs get` との使い分け:

- Meet 議事録の `📖 文字起こし` / `📝 メモ` を section 抽出 / md 変換したい → `docs get`
- Google Docs / Sheets / Slides を docx/xlsx/pptx などのバイナリで保存したい → `drive download --export ...`
- PDF / PPTX / 画像など Drive 上のバイナリをそのまま取得したい → `drive download`

### Drive アップロード

```bash
gws-cli drive upload <local-path> [--folder-id <folder-id>] [--name <drive-name>] [--overwrite] [--keep-forever]
```

- `local-path`: アップロードするローカルファイル（必須）
- `--folder-id`: マイドライブのフォルダ ID（デフォルト: マイドライブ直下）。環境変数 `GWS_CLI_DEFAULT_FOLDER_ID` でも指定可
- `--name`: Drive 上の表示名（デフォルト: ローカルファイルの basename）
- `--overwrite`: 同名ファイルが 1 件だけある場合に revision を上書き
- `--keep-forever`: 作成した revision に `keepRevisionForever` を付与（長期保存したいとき）
- 出力: JSON（`fileId`, `name`, `mimeType`, `webViewLink`, `action`）。`action` は `created` または `updated`

挙動:
- 同名 0 件: 新規作成（`--overwrite` を付けても害はない。新規作成パスに進み `action: created`。gws-cli が作成したファイルになるため、以後 `--overwrite` による revision 上書きが可能）
- 同名 1 件 + `--overwrite`: revision 上書き（stderr に `previousRevisionId` を表示）
- 同名 1 件 + `--overwrite` なし: エラー終了
- 同名 2 件以上: エラー終了（`--overwrite` 有無にかかわらず）
- 共有ドライブ配下のフォルダ指定: エラー終了（マイドライブ限定）
- `--keep-forever` は `action` が `created`（新規作成の初回 revision）でも `updated`（上書き後の最新 revision）でも付与される

`--overwrite` の運用指針:
- ユーザーが「上書き」「最新版に差し替え」「アップデート」と明示したとき: 初回から `--overwrite` を付ける
- ユーザーが「新規アップロード」「保存して」と依頼したとき: `--overwrite` を付けない。同名 1 件で `already exists` エラーが返ったら、既存ファイルを壊す変更になるためユーザーに確認してから `--overwrite` を付けて再実行する
- `--overwrite` は「同名 1 件に対する破壊的な revision 更新」であり、予防的・思考停止で付けるのは避ける

## 典型的なワークフロー

### ワークフロー A: Meet の文字起こしを取得

#### Step 1: イベント ID を特定

Calendar MCP ツールでイベントを検索する。

```
mcp__claude_ai_Google_Calendar__list_events
  calendarId: "primary"
  timeMin: "2026-04-15T00:00:00"
  timeMax: "2026-04-15T23:59:59"
  timeZone: "Asia/Tokyo"
  q: "会議名キーワード"
```

レスポンスの `events[].id` がイベント ID。

#### Step 2: 添付ファイルの fileId を取得

```bash
gws-cli calendar attachments <event-id>
```

レスポンス例:
```json
[{"fileId": "1aBcD...", "title": "Gemini によるメモ", "fileUrl": "https://docs.google.com/...", "mimeType": "application/vnd.google-apps.document"}]
```

添付が複数件ある場合は、文字起こし/メモは Docs 形式で、`title` に「メモ」「Gemini」「議事録」「transcript」などが含まれる。`mimeType: application/vnd.google-apps.document` 以外（PDF など）は `docs get` に渡せないので除外する。候補を特定できない場合はユーザーに選択を確認する。

添付が `[]`（0 件）の場合は以下の可能性をユーザーに確認する: (1) Meet の録画・文字起こし設定が有効でなかった、(2) 会議直後で Gemini のメモ生成がまだ完了していない（数分〜十数分のラグあり）、(3) 別カレンダーのイベントだった。

#### Step 3: 文字起こしテキストを取得

```bash
# 文字起こしのみ抽出（トークン節約）
gws-cli docs get <fileId> --section transcript

# メモ（Gemini 要約）のみ
gws-cli docs get <fileId> --section notes

# 全文
gws-cli docs get <fileId>

# Markdown 形式で取得
gws-cli docs get <fileId> --format md --section transcript
```

### ワークフロー B': Drive のファイルをローカルへ取得

```bash
# バイナリ（PDF / PPTX / 画像など）はそのままダウンロード
gws-cli drive download <fileId>
gws-cli drive download <fileId> ./out/
gws-cli drive download <fileId> ./report.pdf

# Google Docs を docx で保存（既定）
gws-cli drive download <docId>

# Google Docs を PDF で保存
gws-cli drive download <docId> --export pdf

# Sheets を CSV で stdout に流す
gws-cli drive download <sheetId> - --export csv
```

`fileId` は `calendar attachments` の出力や Drive UI の URL から取得できる。

### ワークフロー B: Agent の生成物をマイドライブへアップロード

提案書・スライド・PDF などをローカルで生成した後に Drive へ保存する。

```bash
# 新規アップロード（マイドライブ直下）
gws-cli drive upload ./proposal.pptx

# 指定フォルダに任意の名前で保存
gws-cli drive upload ./report.pdf --folder-id <folder-id> --name "2026Q2 レポート.pdf"

# 既存ファイルを revision として上書き（ファイル名一致が 1 件のみの場合）
gws-cli drive upload ./proposal.pptx --overwrite

# 長期保存（30日 / 100 revision の自動削除対象から除外）
gws-cli drive upload ./proposal.pptx --overwrite --keep-forever
```

レスポンス例:
```json
{
  "fileId": "1AbC...",
  "name": "proposal.pptx",
  "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "webViewLink": "https://drive.google.com/file/d/.../view",
  "action": "created"
}
```

## 注意事項

- Meet の文字起こしと Gemini メモは同一ドキュメント内の別セクションに格納されている（「Docs テキスト取得」節の挙動を参照）
- トークン節約目的なら `--section transcript` / `--section notes` を使い、必要なセクションだけ抽出する
- AI Agent が消費する場合は `--format plain`（デフォルト）が最もコンパクト
- エラー時は stderr にメッセージ + exit 1
- `uv tool install` でインストール済みのためどの作業ディレクトリからでも実行可能
- `drive upload` はマイドライブ専用（共有ドライブは未対応）
- 同じフォルダ・同じ名前の対象に並行アップロードを走らせるとレース条件で重複作成になるため、Agent ワークフローでは逐次実行すること
- バイナリファイル（PPTX/PDF など）の revision は標準で 30 日 / 100 件の早い方が上限。長期保存が必要なら `--keep-forever` を付ける
- `--overwrite` は `drive.file` スコープの仕様上、この CLI で作成したファイルにのみ有効。Drive UI 等で手動作成された同名ファイルは検出はされるが `files.update` が 403 を返すため、別名で新規作成するか Drive UI で削除してから再実行する
  - `drive.file` スコープ: OAuth スコープの一種で、このアプリが作成したファイルにのみ書き込み権限を与える（他アプリ / Drive UI 作成ファイルは読み取り専用になる）。`drive.readonly` が同名検出のためのメタデータ参照、`drive.file` が create / update 実行、という役割分担

## エラー対処

- 403 Forbidden: 主に 2 系統ある。切り分けは「同じ ADC で別コマンド（例: `gws-cli calendar attachments <event-id>`）が通るか」で判定
  - 読み取り系コマンドも 403 → ADC のスコープ不足。`gcloud auth application-default login --scopes=...` を再実行
  - 読み取り系は通るが `drive upload --overwrite` のみ 403 → `drive.file` スコープ制約（下記の `--overwrite` 実行時 403 を参照）
- 404 Not Found: イベント ID / ドキュメント ID / フォルダ ID が不正
- `File '...' already exists`: 同名ファイルが既存。`--overwrite` を付けるか `--name` で別名に変更
- `Multiple files named '...' exist`: 同名ファイルが 2 件以上。Drive UI で整理してから再実行
- `Folder ... is on a shared drive`: 共有ドライブのフォルダは未対応。マイドライブのフォルダ ID を指定
- `--overwrite` 実行時に 403 Forbidden: 対象ファイルがこの CLI 以外（Drive UI 等）で作成されている可能性が高い。`drive.file` スコープは他ツール作成ファイルを更新できない。`--name` で別名にして新規作成するか Drive UI で削除してから再実行
