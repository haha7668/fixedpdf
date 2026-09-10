[English](README.en.md) | [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | 日本語 | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | [Italiano](README.it.md)

# 🧊 Smoothie Reader (Reader3)

> 「AIによって技術が民主化されるとき、美学と人間中心のデザインこそが究極の差別化要因となる。」

Andrej Karpathyの[ミニマリスト・リーダー・プロトタイプ](https://x.com/karpathy/status/1990577951671509438)に触発されたSmoothie Readerは、ローカルで動作するAI搭載電子書籍リーダーです。ワンタップ辞書検索、AI翻訳・対話、TTS読み上げ、ハイライトメモなどの機能を統合し、深い読書のために設計されています。

📖 **内蔵サンプル書籍**：リポジトリにはマルクス・アウレリウスの『自省録』（Project Gutenberg提供）が含まれており、クローン後すぐに体験できます。

<div align="center">
  <img src="assets/library.jpg" width="800" alt="Library"><br>
  <sub>パーソナルライブラリを一望</sub>
</div>

## ✨ 主な機能

- 🔍 **直感的な検索**：テキストを選択するだけでアクションバーが表示されます。**ECDICT（英語）** および中国語のオフライン辞書を内蔵。
- 🤖 **AI強化リーディング**：
  - **インライン翻訳**：文脈に応じた高品質な翻訳を、原文の下にエレガントに埋め込みます。
  - **AIコンパニオン**：ストリーミング対話とマルチターン記憶をサポートするサイドバーAIアシスタント。
  - **幅広い互換性**：OpenAI、Anthropic、Gemini、DeepSeek、Grok、阿里雲百煉、火山引擎、騰訊混元、MiniMax、月之暗面、硅基流動、Cerebras、SambaNova、Groq、Mistral、DeepInfra、Together AI、OpenRouter、智譜AI、ModelScope の計20社のAIプロバイダーを内蔵し、任意のOpenAI互換エンドポイントのカスタム接続もサポート。

<div align="center">
  <img src="assets/reader_AItools.jpg" width="800" alt="AI Tools"><br>
  <sub>選択ツールバー · インライン翻訳 · AIコンパニオンサイドバー</sub>
</div>

- 🔊 **TTS読み上げ**：Edge-TTSを搭載し、中国語・英語の高品質な音声を複数提供。
- ✏️ **ハイライト＆メモ**：5色ハイライト、インライン注釈、ブックマーク。データはすべてブラウザの**localStorage**に保存されます。

<div align="center">
  <img src="assets/reader_catelog.jpg" width="800" alt="Reading Layout"><br>
  <sub>3カラム閲覧：目次ナビ · 没入型テキスト · マルチカラーハイライト</sub>
</div>

- 🎨 **ミニマルな美学**：厳選された6つのテーマと柔軟な3カラムレイアウト（目次/本文/AI）、あらゆるデバイスに対応。

<div align="center">
  <img src="assets/reader_setting.jpg" width="800" alt="Settings"><br>
  <sub>テーマ、タイポグラフィ、辞書、AIモデル — ワンストップ設定</sub>
</div>

## 🚀 クイックスタート

本プロジェクトは [uv](https://docs.astral.sh/uv/) でPython環境と依存関係を管理しています。

### 1. uvのインストール
Python 3.10以上がインストールされていることを確認し、`uv`をインストールします：
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 電子書籍のインポートと起動
```bash
# EPUB電子書籍をインポート
uv run reader3.py your_book.epub

# サーバーを起動
uv run server.py
```
ブラウザでアクセス：👉 **http://localhost:8123**

### 3. AIの設定
読書インターフェースに入り、左上の**設定 (Settings)** から**AIプロバイダー**とAPIキーを構成します（例：[Gemini Keyを無料で取得](https://aistudio.google.com/apikey)）。

> [!TIP]
> **🚀 イースターエッグ**：ページ上のどこでも **`↑ ↑ ↓ ↓ ← → ← → B A`**（コナミコマンド）を入力すると、隠された**高度なAIルーティングパネル**がアンロックされます。

## 🛡️ プライバシー
- **ローカル優先**：AIやTTSを明示的にトリガーしない限り、データがデバイスを離れることはありません。
- **アカウント不要**：データはブラウザの`localStorage`のみに保持されます。

## 📚 ユーザーガイド
詳細な設定手順（オフライン辞書のダウンロード、マルチデバイスアクセス、ポート設定）については、[ユーザーガイド](docs/GUIDE.md)を参照してください。

## 📄 ライセンス
[MIT License](LICENSE)
