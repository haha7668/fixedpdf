[English](README.en.md) | [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | 한국어 | [Español](README.es.md) | [Français](README.fr.md) | [Italiano](README.it.md)

# 🧊 Smoothie Reader (Reader3)

> "기술이 AI에 의해 민주화될 때, 미학과 인간 중심의 디자인이 궁극적인 차별점이 됩니다."

Andrej Karpathy의 [미니멀리스트 리더 프로토타입](https://x.com/karpathy/status/1990577951671509438)에서 영감을 받은 Smoothie Reader는 로컬에서 실행되는 AI 기반 전자책 리더기입니다. 원터치 사전 검색, AI 번역 및 대화, TTS 읽기, 하이라이트 노트 등의 기능을 통합하여 깊은 독서를 위해 설계되었습니다.

📖 **내장 샘플 도서**: 저장소에는 마르쿠스 아우렐리우스의 "명상록" (Project Gutenberg 제공)이 포함되어 있어, 클론 후 바로 체험할 수 있습니다.

<div align="center">
  <img src="assets/library.jpg" width="800" alt="Library"><br>
  <sub>개인 서재를 한눈에</sub>
</div>

## ✨ 핵심 기능

- 🔍 **직관적 탐색**: 텍스트를 선택하기만 하면 액션 바가 나타납니다. **ECDICT (영어)** 및 중국어 오프라인 사전 내장.
- 🤖 **AI 강화 독서**:
  - **인라인 번역**: 문맥을 반영한 고품질 번역이 원문 아래에 우아하게 삽입됩니다.
  - **AI 동반자**: 스트리밍 대화와 다중 턴 기억을 지원하는 사이드바 AI 어시스턴트.
  - **폭넓은 호환성**: OpenAI, Anthropic, Gemini, DeepSeek, Grok, 阿里云百炼, 火山引擎, 腾讯混元, MiniMax, Moonshot, SiliconFlow, Cerebras, SambaNova, Groq, Mistral, DeepInfra, Together AI, OpenRouter, 智谱AI, ModelScope 총 20개 AI 서비스 제공업체를 내장하고, 임의의 OpenAI 호환 엔드포인트 커스텀 연결도 지원.

<div align="center">
  <img src="assets/reader_AItools.jpg" width="800" alt="AI Tools"><br>
  <sub>선택 도구 모음 · 인라인 번역 · AI 동반자 사이드바</sub>
</div>

- 🔊 **TTS 읽기**: Edge-TTS 기반으로 중국어·영어 고품질 음성을 다수 제공.
- ✏️ **하이라이트 및 노트**: 5가지 색상 하이라이트, 인라인 주석, 북마크. 모든 데이터는 브라우저의 **localStorage**에 저장됩니다.

<div align="center">
  <img src="assets/reader_catelog.jpg" width="800" alt="Reading Layout"><br>
  <sub>3단 독서: 목차 탐색 · 몰입형 텍스트 · 멀티 컬러 하이라이트</sub>
</div>

- 🎨 **미니멀리즘 미학**: 엄선된 6가지 테마와 유연한 3단 레이아웃 (목차/본문/AI), 모든 기기에 최적화.

<div align="center">
  <img src="assets/reader_setting.jpg" width="800" alt="Settings"><br>
  <sub>테마, 타이포그래피, 사전, AI 모델 — 올인원 설정</sub>
</div>

## 🚀 빠른 시작

이 프로젝트는 [uv](https://docs.astral.sh/uv/)를 사용하여 Python 환경과 의존성을 관리합니다.

### 1. uv 설치
Python 3.10 이상이 필요합니다. `uv`를 설치하세요:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 전자책 가져오기 및 실행
```bash
# EPUB 전자책 가져오기
uv run reader3.py your_book.epub

# 서버 시작
uv run server.py
```
브라우저에서 접속: 👉 **http://localhost:8123**

### 3. AI 설정
독서 인터페이스에서 왼쪽 상단의 **설정 (Settings)**을 클릭하여 **AI 제공업체**와 API 키를 구성하세요 (예: [무료 Gemini 키 받기](https://aistudio.google.com/apikey)).

> [!TIP]
> **🚀 이스터 에그**: 페이지 어디에서나 **`↑ ↑ ↓ ↓ ← → ← → B A`** (코나미 커맨드)를 입력하면 숨겨진 **고급 AI 라우팅 패널**이 잠금 해제됩니다.

## 🛡️ 개인정보 보호
- **로컬 우선**: AI나 TTS를 명시적으로 호출하지 않는 한 데이터가 기기를 떠나지 않습니다.
- **계정 불필요**: 데이터는 브라우저의 `localStorage`에만 보관됩니다.

## 📚 사용 가이드
상세한 구성 지침 (오프라인 사전 다운로드, 다중 기기 접속, 포트 설정)은 [사용 가이드](docs/GUIDE.md)를 참조하세요.

## 📄 라이선스
[MIT License](LICENSE)
