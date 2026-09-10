[English](README.en.md) | [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | [Français](README.fr.md) | Italiano

# 🧊 Smoothie Reader (Reader3)

> "Quando la tecnologia viene democratizzata dall'IA, l'estetica e il design incentrato sull'uomo diventano i differenziatori finali."

Ispirato al [prototipo di lettore minimalista](https://x.com/karpathy/status/1990577951671509438) di Andrej Karpathy, Smoothie Reader è un lettore di e-book alimentato dall'IA che funziona localmente. Integra ricerca di parole, traduzione e dialogo IA, lettura TTS e note evidenziate, progettato per la lettura profonda.

📖 **Libro di esempio incluso**: Il repository include "Meditazioni" di Marco Aurelio (via Project Gutenberg), pronto da esplorare dopo il clone.

<div align="center">
  <img src="assets/library.jpg" width="800" alt="Library"><br>
  <sub>La tua biblioteca personale a colpo d'occhio</sub>
</div>

## ✨ Funzionalità Principali

- 🔍 **Scoperta Intuitiva**: Evidenzia qualsiasi testo per rivelare la barra delle azioni. Supporto integrato per **ECDICT** (Inglese) e dizionari cinesi offline.
- 🤖 **Lettura Potenziata dall'IA**:
  - **Traduzione in Linea**: Traduzioni contestuali di alta qualità elegantemente incorporate sotto il testo originale.
  - **Compagno IA**: Un assistente IA nella barra laterale che supporta il dialogo in streaming e la memoria multi-turno.
  - **Ampia Compatibilità**: Supporto integrato per OpenAI, Anthropic, Gemini, DeepSeek, Grok, Alibaba Cloud Bailian, Volcengine, Tencent Hunyuan, MiniMax, Moonshot, SiliconFlow, Cerebras, SambaNova, Groq, Mistral, DeepInfra, Together AI, OpenRouter, Zhipu AI e ModelScope — 20 provider IA in totale, più endpoint personalizzati compatibili con OpenAI.

<div align="center">
  <img src="assets/reader_AItools.jpg" width="800" alt="AI Tools"><br>
  <sub>Barra di selezione · Traduzione in linea · Pannello laterale del compagno IA</sub>
</div>

- 🔊 **Lettura TTS**: Alimentato da Edge-TTS con molteplici voci di alta qualità in cinese e inglese.
- ✏️ **Evidenziazioni e Note**: Evidenziazione in 5 colori, annotazioni in linea e segnalibri — tutto conservato nel **localStorage** del tuo browser.

<div align="center">
  <img src="assets/reader_catelog.jpg" width="800" alt="Reading Layout"><br>
  <sub>Lettura a 3 colonne: navigazione ToC · Testo immersivo · Evidenziazioni multicolore</sub>
</div>

- 🎨 **Estetica Minimalista**: 6 temi curati e un layout flessibile a 3 colonne (ToC/Contenuto/IA), ottimizzato per tutti i dispositivi.

<div align="center">
  <img src="assets/reader_setting.jpg" width="800" alt="Settings"><br>
  <sub>Temi, tipografia, dizionari, modelli IA — configurazione tutto in uno</sub>
</div>

## 🚀 Avvio Rapido

Questo progetto utilizza [uv](https://docs.astral.sh/uv/) per gestire l'ambiente Python e le dipendenze.

### 1. Installare uv
Assicurati che Python 3.10+ sia disponibile. Installa `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Importare un Libro e Avviare
```bash
# Importa un e-book EPUB
uv run reader3.py your_book.epub

# Avvia il server
uv run server.py
```
Accedi al lettore su: 👉 **http://localhost:8123**

### 3. Configurare l'IA
Entra nell'interfaccia di lettura, clicca su **Impostazioni (Settings)** in alto a sinistra e configura il tuo **Provider IA** e chiave API (es. [ottieni una Gemini Key gratuita](https://aistudio.google.com/apikey)).

> [!TIP]
> **🚀 Easter Egg**: In qualsiasi punto della pagina, inserisci **`↑ ↑ ↓ ↓ ← → ← → B A`** (Codice Konami) per sbloccare il **Pannello Avanzato di Routing IA** nascosto.

## 🛡️ Privacy
- **Locale Prima di Tutto**: Nessun dato lascia il tuo dispositivo a meno che tu non attivi esplicitamente una richiesta IA o TTS.
- **Senza Account**: I tuoi dati rimangono esclusivamente nel `localStorage` del tuo browser.

## 📚 Guida Utente
Per configurazioni dettagliate (dizionari offline, accesso multi-dispositivo, impostazioni porta), consulta la [Guida Utente](docs/GUIDE.md).

## 📄 Licenza
[MIT License](LICENSE)
