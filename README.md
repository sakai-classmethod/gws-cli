# gws-cli

Google Workspace リソース（Calendar 添付ファイル、Google Docs テキスト）を読み取る CLI ツール。
主に Google Meet の文字起こしテキスト取得に使用する。

## 目次

- [プロジェクト概要](#プロジェクト概要)
- [対象ユーザー](#対象ユーザー)
- [前提条件](#前提条件)
- [使い方](#使い方)
  - [インストール](#インストール)
  - [設定](#設定)
  - [実行](#実行)
- [関連ドキュメント](#関連ドキュメント)

## プロジェクト概要

`gws-cli` を使うと、Google Workspace のリソースをコマンドラインから取得できる。

- Calendar イベントの添付ファイル一覧を JSON で取得
- Google Docs のテキストをプレーンテキストまたは Markdown 形式で取得
- Meet の文字起こし（`📖 文字起こし`）やメモ（`📝 メモ`）をセクション単位で抽出

Claude Code のスキルとして組み込むことで、会議の文字起こし取得から要約・分析までのワークフローを自動化できる。

## 対象ユーザー

このプロジェクトは、Claude Code のスキルとして Meet の文字起こしを自動取得し、要約や分析を行いたいユーザー向け。

## 前提条件

`gws-cli` を使用するには、以下が必要:

- Python 3.13 以上
- [uv](https://docs.astral.sh/uv/) パッケージマネージャー
- Google Cloud の Application Default Credentials（ADC）が認証済みであること
  - 必要なスコープ: `calendar.readonly`, `drive.readonly`

## 使い方

### インストール

```bash
uv tool install git+https://github.com/sakai-classmethod/gws-cli
```

### 設定

1. ADC の認証を実行（未認証の場合）

    ```bash
    gcloud auth application-default login \
      --scopes="openid,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/drive.readonly"
    ```

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
