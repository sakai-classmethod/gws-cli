# gws-cli

Google Workspace リソースを扱う CLI ツール。

- 読み取り: Calendar イベント (添付 + 説明文の Drive リンクを構造化抽出)、Calendar 一覧、Google Docs テキスト（Meet 文字起こし取得の自動化向け）、Drive 上の任意ファイルのダウンロード
- 書き込み: ローカルファイルを自分のマイドライブにアップロード（Agent 生成物の PPTX/PDF などを対象）

## 目次

- [プロジェクト概要](#プロジェクト概要)
- [対象ユーザー](#対象ユーザー)
- [前提条件](#前提条件)
- [使い方](#使い方)
  - [インストール](#インストール)
  - [設定](#設定)
  - [実行](#実行)
    - [Calendar イベント取得 (event get / event list)](#calendar-イベント取得-event-get--event-list)
    - [Calendar 一覧](#calendar-一覧)
    - [Calendar 添付ファイル取得 (deprecated)](#calendar-添付ファイル取得-deprecated)
    - [Docs テキスト取得](#docs-テキスト取得)
    - [Drive アップロード](#drive-アップロード)
    - [Drive ダウンロード](#drive-ダウンロード)
    - [典型的なワークフロー: Meet の文字起こし取得](#典型的なワークフロー-meet-の文字起こし取得)
- [関連ドキュメント](#関連ドキュメント)

## プロジェクト概要

`gws-cli` を使うと、Google Workspace のリソースをコマンドラインから取得できる。

- Calendar イベント詳細を取得し、添付ファイルと説明文中の Drive リンクを 1 つの `links` フィールドに構造化抽出
- 期間とキーワードでカレンダーイベントを検索し、各イベントごとに同じスキーマの `links` を付けて返す
- 自分がアクセス可能なカレンダー一覧を取得（`primary` 以外のカレンダー ID を解決）
- Google Docs のテキストをプレーンテキストまたは Markdown 形式で取得
- Meet の文字起こし（`📖 文字起こし`）やメモ（`📝 メモ`）をセクション単位で抽出
- マイドライブへのファイルアップロード（上書き・revision 保持に対応）
- Drive 上の任意ファイルのダウンロード（バイナリ + Google native のエクスポート、共有ドライブ対応）

Claude Code のスキルとして組み込むことで、会議の文字起こし取得から要約・分析、成果物の Drive 保存までのワークフローを自動化できる。

## 対象ユーザー

このプロジェクトは、Claude Code のスキルとして Meet の文字起こしを自動取得し、要約や分析を行いたいユーザー向け。

## 前提条件

`gws-cli` を使用するには、以下が必要:

- Python 3.13 以上
- [uv](https://docs.astral.sh/uv/) パッケージマネージャー
- Google Cloud の Application Default Credentials（ADC）が認証済みであること
  - 必要なスコープ:
    - `calendar.readonly` — Calendar イベント / カレンダー一覧読み取り（`calendar event get|list`, `calendar calendars`, `calendar attachments`）
    - `drive.readonly` — Google Docs 本文読み取り + Drive upload 時の同名ファイル事前検出（`docs get`, `drive upload`）
    - `drive.file` — この CLI が作成したファイルへの書き込み（`drive upload`）
  - CLI は用途別にスコープを使い分けて認証情報を取得する（例: `calendar` コマンドは `calendar.readonly` のみを要求）
  - ただし `gcloud auth application-default login` で取得する ADC は全スコープを事前に grant しておく必要がある
  - `drive.file` のみの付与では `drive upload` の同名ファイル検出が機能しない（手動作成されたファイルが見えず silent duplicate になる）ため `drive.readonly` と併用すること

## 使い方

### インストール

```bash
uv tool install git+https://github.com/sakai-classmethod/gws-cli
```

### 設定

1. Google Cloud プロジェクトで OAuth 2.0 クライアント（Desktop アプリ）を作成し、JSON をダウンロード

    `drive.file` は「この OAuth クライアント経由で作成されたファイル」に書き込みを限定するスコープ。gcloud デフォルトの共有クライアント（Cloud SDK）を使うと「自分が gcloud 経由で触った全ファイル」が対象に広がるため、本 CLI 専用の OAuth クライアントを使うことを推奨する。

2. ADC の認証を実行（未認証の場合）

    ```bash
    gcloud auth application-default login \
      --client-id-file=<path/to/client_secret.json> \
      --scopes="https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/drive.file"
    ```

    `cloud-platform` は gcloud が `--client-id-file` 使用時に必須で要求するスコープ（gcloud 自身の ADC 動作保証のため）。本 CLI からは参照しないが、付与しないと `gcloud auth application-default login` が失敗する。`openid` / `userinfo.email` は本 CLI からは参照しないので含めない。

### 実行

#### Calendar イベント取得 (event get / event list)

```bash
gws-cli calendar event get <event-id> [--calendar-id <calendar-id>]

gws-cli calendar event list \
  [--calendar-id <id>] \
  [--time-min <iso8601>] [--time-max <iso8601>] \
  [--q <query>] [--event-type <type>]... \
  [--order-by startTime|updated] \
  [--page-size <n>] [--page-token <token>] \
  [--time-zone <iana-tz>] \
  [--show-deleted] \
  [--all-pages]
```

`event get` は単一イベントの取得、`event list` は期間検索。どちらも Calendar API の生レスポンスに以下 2 フィールドを必ず付与する。

- `attachments`: Calendar API の `attachments` 配列（API 上は省略され得るが本コマンドは常に空配列以上を返す）
- `links`: 添付ファイルと説明文の Drive リンクを統合・dedup したリスト

```json
{
  "url": "https://docs.google.com/document/d/.../edit",
  "fileId": "1aBcD...",
  "mimeType": "application/vnd.google-apps.document",
  "title": "Gemini によるメモ",
  "sources": ["event.attachments", "event.description"],
  "sourceUrls": ["https://docs.google.com/document/d/.../edit"]
}
```

`fileId` で dedup し、attachments 由来と description 由来の両方に同じ Doc が現れた場合は `sources` でマージする。description は anchor タグ抽出 + 平文 URL regex の二段構えで HTML / 平文どちらにも耐える。Drive で削除済みの参照も `links` に含める（Calendar 上に残っている事実を保持し、Drive 側の生死検証はしない）。

`event list` の出力は envelope 形式:

```json
{ "items": [<event with attachments and links>], "nextPageToken": "<optional>", "nextSyncToken": "<optional>" }
```

`--all-pages` を指定すると内部でページを連結し `items` に全件集約、`nextPageToken` は省略する。`--all-pages` には `--time-min` と `--time-max` の両方が必須（未指定は exit 2 で拒否、長期レンジ全件取得の事故防止）。

#### Calendar 一覧

```bash
gws-cli calendar calendars
```

`{"items": [...]}` envelope を返す。`items[i]` は CalendarList resource (`id`, `summary`, `accessRole` など)。`event get` / `event list` の `--calendar-id` に渡すカレンダー ID を解決するために使う。

#### Calendar 添付ファイル取得 (deprecated)

```bash
gws-cli calendar attachments <event-id> [--calendar-id <calendar-id>]
```

互換維持のために残しているが deprecated。実行時に stderr へ警告を出力し、次メジャーで削除予定。新規利用は `gws-cli calendar event get` に統一する（`event get` は本コマンドの返り値に相当する `attachments` を含む event 全体を返す）。

#### Docs テキスト取得

```bash
gws-cli docs get <doc-id> [--format plain|md] [--section transcript|notes]
```

| パラメータ | 説明 | デフォルト |
| :--- | :--- | :--- |
| `doc-id` | Google Docs のドキュメント ID | (必須) |
| `--format` | 出力形式（`plain` または `md`） | `plain` |
| `--section` | セクション抽出（`transcript` で文字起こしのみ、`notes` でメモのみ） | なし（全文） |

#### Drive アップロード

```bash
gws-cli drive upload <local-path> [--folder-id <folder-id>] [--name <drive-name>] [--overwrite] [--keep-forever]
```

| パラメータ | 説明 | デフォルト |
| :--- | :--- | :--- |
| `local-path` | アップロードするローカルファイル | (必須) |
| `--folder-id` | 保存先のマイドライブフォルダ ID | マイドライブ直下 |
| `--name` | Drive 上の表示名 | ローカルファイルの basename |
| `--overwrite` | 同名ファイルが 1 件だけある場合に revision を上書きする | off |
| `--keep-forever` | 作成する revision に `keepRevisionForever` を付ける（200 件上限あり） | off |

環境変数 `GWS_CLI_DEFAULT_FOLDER_ID` を設定すると `--folder-id` 未指定時の既定値になる。

挙動:

- 同名ファイルが 0 件: 新規作成（`action: "created"`）
- 同名ファイルが 1 件 かつ `--overwrite` あり: revision 上書き（`action: "updated"`）
- 同名ファイルが 1 件 かつ `--overwrite` なし: エラー終了
- 同名ファイルが 2 件以上: `--overwrite` の有無にかかわらずエラー終了（fileId を stderr に列挙）
- `--folder-id` が共有ドライブ配下のフォルダを指している場合はエラー終了（マイドライブ限定）

上書き時は stderr に `Overwriting existing file: ...` を出力し、stdout には JSON を出力する。

```json
{
  "fileId": "1AbC...",
  "name": "proposal.pptx",
  "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "webViewLink": "https://drive.google.com/file/d/.../view",
  "action": "created"
}
```

revision の履歴は Drive UI の「版の管理」または Revisions API から復元できる。バイナリファイル（PPTX/PDF など）はデフォルトで 30 日 / 100 revision のうち早い方が上限なので、長期保存が必要なときは `--keep-forever` を使う。

制約:

- 同じフォルダ・同じ名前の対象に対して並行に `drive upload` を走らせると、同名判定と新規作成/上書きの間でレースが発生し、予期しない重複作成や stale な revision ログが出る可能性がある。Agent ワークフローで同一ターゲットを操作する場合は逐次実行を推奨する
- `--overwrite` 実行中に `revisions.list` が API エラーになった場合、ロールバック情報が取得できないためアップロードは中断する（fail-closed）
- `--overwrite` は `drive.file` スコープの仕様上、この CLI（同じ OAuth クライアント）で作成したファイルにのみ適用可能。Drive UI や他ツールで手動作成された同名ファイルは `find_existing` では検出できるが `files.update` が 403 を返す。手動作成ファイルを更新したい場合は Drive UI で一度削除するか、`--name` で別名を指定して新規作成すること

#### Drive ダウンロード

```bash
gws-cli drive download <file-id> [<dest>] [--export <format>] [--overwrite]
```

| パラメータ | 説明 | デフォルト |
| :--- | :--- | :--- |
| `file-id` | Drive のファイル ID | (必須) |
| `dest` | 保存先（ファイル / ディレクトリ / `-` で stdout） | カレントディレクトリ |
| `--export` | Google native のエクスポート形式（shortcut または MIME） | タイプ別の既定値 |
| `--overwrite` | 既存ローカルファイルがあれば上書き | off |

`--export` のショートカット: `pdf`, `docx`, `xlsx`, `pptx`, `png`, `jpeg`, `csv`, `txt`, `rtf`, `odt`, `ods`, `epub`, `tsv`。MIME を直接渡すこともできる（例: `--export application/pdf`）。

Google native の既定エクスポート:

| 種別 | mimeType | 既定 export | 拡張子 |
| :--- | :--- | :--- | :--- |
| Docs | `application/vnd.google-apps.document` | docx | `.docx` |
| Sheets | `application/vnd.google-apps.spreadsheet` | xlsx | `.xlsx` |
| Slides | `application/vnd.google-apps.presentation` | pptx | `.pptx` |
| Drawings | `application/vnd.google-apps.drawing` | png | `.png` |

挙動:

- `dest` 省略 / 既存ディレクトリ指定 / 末尾 `/`: その下に Drive 名 (+ 拡張子) で保存
- `dest` ファイルパス指定: そのパスに保存（拡張子と export 形式が不一致なら stderr に警告）
- `dest` が `-`: 内容を stdout、メタデータ JSON を stderr に出力（TTY 直書きは拒否）
- 既存ローカルファイル + `--overwrite` なし: エラー終了
- 書き込みは同一ディレクトリの `tmp` ファイル → `os.replace` のアトミック置換（途中失敗時に半端なファイルを残さない）
- `mimeType` が フォルダ / shortcut / form / site / `audio/*` / `video/*` などの場合はエラー終了
- `files.export` の 10MB 出力上限に該当する場合は専用エラー（Drive UI / Takeout を案内）

ファイル保存時の出力例（stdout、`-` 指定時は stderr）:

```json
{
  "fileId": "1AbC...",
  "name": "proposal.pptx",
  "mimeType": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "exportMime": null,
  "localPath": "/path/to/proposal.pptx",
  "bytesWritten": 524288,
  "source": "media",
  "action": "downloaded",
  "headRevisionId": "0BxYz...",
  "modifiedTime": "2026-05-01T03:21:11.123Z",
  "md5Checksum": "deadbeef...",
  "size": "524288",
  "webViewLink": "https://drive.google.com/file/d/.../view"
}
```

`source` は `"media"`（バイナリ DL）または `"export"`（Google native のエクスポート）。`md5Checksum` は `source=export` の場合 `null` になる（エクスポート結果は元ファイルのハッシュではないため）。

#### 典型的なワークフロー: Meet の文字起こし取得

1. 期間とキーワードでイベントを検索

    ```bash
    gws-cli calendar event list \
      --time-min 2026-04-15T00:00:00+09:00 \
      --time-max 2026-04-15T23:59:59+09:00 \
      --time-zone Asia/Tokyo \
      --q '会議名キーワード'
    ```

2. 当該イベントの `links` から Doc の `fileId` を取得

    ```bash
    gws-cli calendar event get <event-id>
    ```

   Meet の Gemini メモは通常 `mimeType: application/vnd.google-apps.document` かつ `title` に「Gemini によるメモ」「メモ - 」を含む。複数候補がある場合は `mimeType` で Docs 形式に絞り、`title` / `sources` で判別する。

3. 文字起こしテキストを取得

    ```bash
    # 文字起こしのみ抽出（トークン節約）
    gws-cli docs get <fileId> --section transcript

    # メモ（Gemini 要約）のみ
    gws-cli docs get <fileId> --section notes

    # Markdown 形式で全文取得
    gws-cli docs get <fileId> --format md
    ```

## 関連ドキュメント

- [skills/gws-cli/SKILL.md](skills/gws-cli/SKILL.md) - Claude Code スキルとしての利用ガイド
- [Google Calendar API](https://developers.google.com/calendar/api/v3/reference) - Calendar API リファレンス
- [Google Drive API](https://developers.google.com/drive/api/v3/reference) - Drive API リファレンス（Docs エクスポートに使用）
