---
name: gws-cli
description: |
  Google Workspace リソース（Calendar 添付ファイル、Google Docs テキスト）を取得する CLI スキル。
  以下の場面で使用する:
  - 会議の文字起こしを取得したいとき（「文字起こし取って」「トランスクリプト取得」「議事録の元データ」）
  - Calendar イベントの添付ファイルを確認したいとき（「添付ファイル一覧」「Meet のドキュメント」）
  - Google Docs の本文をテキストで取得したいとき（「Docs の中身を取得」「ドキュメント読んで」）
  - Meet の会議内容を要約・分析する前段階として元データが必要なとき
allowed-tools:
  - "Bash(gws-cli:*)"
  - "mcp__claude_ai_Google_Calendar__gcal_list_events"
  - "mcp__claude_ai_Google_Calendar__gcal_get_event"
---

# gws-cli: Google Workspace 読み取り CLI

Google Workspace のリソースを読み取る CLI ツール。
主に Meet の文字起こしテキスト取得に使用する。

## 前提条件

- リポジトリ: `github.com/sakai-classmethod/gws-cli`
- ADC 認証済み（`calendar.readonly` + `drive.readonly` スコープ）
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

## 典型的なワークフロー

Meet の文字起こしを取得する手順:

### Step 1: イベント ID を特定

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

### Step 2: 添付ファイルの fileId を取得

```bash
gws-cli calendar attachments <event-id>
```

レスポンス例:
```json
[{"fileId": "1aBcD...", "title": "Gemini によるメモ", "fileUrl": "https://docs.google.com/..."}]
```

### Step 3: 文字起こしテキストを取得

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

## 注意事項

- `--section transcript` を使うと「📖 文字起こし」セクション以降のみ抽出される（トークン節約に有効）
- Meet の文字起こしと Gemini メモは同一ドキュメント内の別セクションに格納されている
- AI Agent が消費する場合は `--format plain`（デフォルト）が最もコンパクト
- エラー時は stderr にメッセージ + exit 1
- `uv tool install` でインストール済みのためどの作業ディレクトリからでも実行可能

## エラー対処

- 403 Forbidden: ADC のスコープ不足。`gcloud auth application-default login --scopes=...` を再実行
- 404 Not Found: イベント ID またはドキュメント ID が不正
