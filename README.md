# gws-cli

Google Workspace リソースを扱う CLI ツール。

- 読み取り: Calendar 添付ファイル、Google Docs テキスト（Meet 文字起こし取得の自動化向け）
- 書き込み: ローカルファイルを自分のマイドライブにアップロード（Agent 生成物の PPTX/PDF などを対象）

## 目次

- [プロジェクト概要](#プロジェクト概要)
- [対象ユーザー](#対象ユーザー)
- [前提条件](#前提条件)
- [使い方](#使い方)
  - [インストール](#インストール)
  - [設定](#設定)
  - [実行](#実行)
    - [Calendar 添付ファイル取得](#calendar-添付ファイル取得)
    - [Docs テキスト取得](#docs-テキスト取得)
    - [Drive アップロード](#drive-アップロード)
    - [典型的なワークフロー: Meet の文字起こし取得](#典型的なワークフロー-meet-の文字起こし取得)
- [関連ドキュメント](#関連ドキュメント)

## プロジェクト概要

`gws-cli` を使うと、Google Workspace のリソースをコマンドラインから取得できる。

- Calendar イベントの添付ファイル一覧を JSON で取得
- Google Docs のテキストをプレーンテキストまたは Markdown 形式で取得
- Meet の文字起こし（`📖 文字起こし`）やメモ（`📝 メモ`）をセクション単位で抽出
- マイドライブへのファイルアップロード（上書き・revision 保持に対応）

Claude Code のスキルとして組み込むことで、会議の文字起こし取得から要約・分析、成果物の Drive 保存までのワークフローを自動化できる。

## 対象ユーザー

このプロジェクトは、Claude Code のスキルとして Meet の文字起こしを自動取得し、要約や分析を行いたいユーザー向け。

## 前提条件

`gws-cli` を使用するには、以下が必要:

- Python 3.13 以上
- [uv](https://docs.astral.sh/uv/) パッケージマネージャー
- Google Cloud の Application Default Credentials（ADC）が認証済みであること
  - 必要なスコープ:
    - `calendar.readonly` — Calendar 添付ファイル読み取り（`calendar attachments` コマンド）
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

#### Calendar 添付ファイル取得

```bash
gws-cli calendar attachments <event-id> [--calendar-id <calendar-id>]
```

| パラメータ | 説明 | デフォルト |
| :--- | :--- | :--- |
| `event-id` | Google Calendar のイベント ID | (必須) |
| `--calendar-id` | カレンダー ID | `primary` |

出力は JSON 配列（`fileId`, `title`, `fileUrl`, `mimeType`）。添付なしの場合は `[]` を返す。

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

#### 典型的なワークフロー: Meet の文字起こし取得

1. Calendar からイベント ID を特定
2. 添付ファイルの `fileId` を取得

    ```bash
    gws-cli calendar attachments <event-id>
    ```

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
