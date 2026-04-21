---
name: gws-cli
description: |
  Google Workspace リソース（Calendar 添付ファイル、Google Docs テキスト、マイドライブへのアップロード）を扱う CLI スキル。
  以下の場面で使用する:
  - 会議の文字起こしを取得したいとき（「文字起こし取って」「トランスクリプト取得」「議事録の元データ」）
  - Calendar イベントの添付ファイルを確認したいとき（「添付ファイル一覧」「Meet のドキュメント」）
  - Google Docs の本文をテキストで取得したいとき（「Docs の中身を取得」「ドキュメント読んで」）
  - Meet の会議内容を要約・分析する前段階として元データが必要なとき
  - ローカルファイルをマイドライブにアップロードしたいとき（「Drive に上げて」「PPTX をマイドライブに保存」「生成した PDF をアップロード」）
  - Agent が生成した成果物（提案書・スライド・レポートなど）を Drive へ保存したいとき
allowed-tools:
  - "Bash(gws-cli:*)"
  - "mcp__claude_ai_Google_Calendar__gcal_list_events"
  - "mcp__claude_ai_Google_Calendar__gcal_get_event"
---

# gws-cli: Google Workspace CLI

Google Workspace のリソースを読み書きする CLI ツール。

- 読み取り: Calendar 添付ファイル / Google Docs テキスト（Meet 文字起こし取得など）
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
- 同名 0 件: 新規作成
- 同名 1 件 + `--overwrite`: revision 上書き（stderr に `previousRevisionId` を表示）
- 同名 1 件 + `--overwrite` なし: エラー終了
- 同名 2 件以上: エラー終了（`--overwrite` 有無にかかわらず）
- 共有ドライブ配下のフォルダ指定: エラー終了（マイドライブ限定）

## 典型的なワークフロー

### ワークフロー A: Meet の文字起こしを取得

#### Step 1: イベント ID を特定

Calendar MCP ツールでイベントを検索する。

```
mcp__claude_ai_Google_Calendar__gcal_list_events
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
[{"fileId": "1aBcD...", "title": "Gemini によるメモ", "fileUrl": "https://docs.google.com/..."}]
```

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

- `--section transcript` を使うと「📖 文字起こし」セクション以降のみ抽出される（トークン節約に有効）
- Meet の文字起こしと Gemini メモは同一ドキュメント内の別セクションに格納されている
- AI Agent が消費する場合は `--format plain`（デフォルト）が最もコンパクト
- エラー時は stderr にメッセージ + exit 1
- `uv tool install` でインストール済みのためどの作業ディレクトリからでも実行可能
- `drive upload` はマイドライブ専用（共有ドライブは未対応）
- 同じフォルダ・同じ名前の対象に並行アップロードを走らせるとレース条件で重複作成になるため、Agent ワークフローでは逐次実行すること
- バイナリファイル（PPTX/PDF など）の revision は標準で 30 日 / 100 件の早い方が上限。長期保存が必要なら `--keep-forever` を付ける
- `--overwrite` は `drive.file` スコープの仕様上、この CLI で作成したファイルにのみ有効。Drive UI 等で手動作成された同名ファイルは検出はされるが `files.update` が 403 を返すため、別名で新規作成するか Drive UI で削除してから再実行する

## エラー対処

- 403 Forbidden: ADC のスコープ不足。`gcloud auth application-default login --scopes=...` を再実行
- 404 Not Found: イベント ID / ドキュメント ID / フォルダ ID が不正
- `File '...' already exists`: 同名ファイルが既存。`--overwrite` を付けるか `--name` で別名に変更
- `Multiple files named '...' exist`: 同名ファイルが 2 件以上。Drive UI で整理してから再実行
- `Folder ... is on a shared drive`: 共有ドライブのフォルダは未対応。マイドライブのフォルダ ID を指定
- `--overwrite` 実行時に 403 Forbidden: 対象ファイルがこの CLI 以外（Drive UI 等）で作成されている可能性が高い。`drive.file` スコープは他ツール作成ファイルを更新できない。`--name` で別名にして新規作成するか Drive UI で削除してから再実行
