[English](README.en.md) | [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | [Español](README.es.md) | Français | [Italiano](README.it.md)

# 🧊 Smoothie Reader (Reader3)

> "Lorsque la technologie est démocratisée par l'IA, l'esthétique et le design centré sur l'humain deviennent les ultimes différenciateurs."

Inspiré par le [prototype de lecteur minimaliste](https://x.com/karpathy/status/1990577951671509438) d'Andrej Karpathy, Smoothie Reader est un lecteur de livres numériques alimenté par l'IA qui fonctionne localement. Il intègre la recherche de mots, la traduction et le dialogue IA, la lecture TTS et les notes surlignées, conçu pour une lecture approfondie.

📖 **Livre exemple inclus** : Le dépôt contient les « Méditations » de Marc Aurèle (via Project Gutenberg), prêt à explorer après le clonage.

<div align="center">
  <img src="assets/library.jpg" width="800" alt="Library"><br>
  <sub>Votre bibliothèque personnelle en un coup d'œil</sub>
</div>

## ✨ Fonctionnalités Principales

- 🔍 **Découverte Intuitive** : Surlignez n'importe quel texte pour révéler la barre d'action. Prise en charge intégrée d'**ECDICT** (Anglais) et de dictionnaires chinois hors ligne.
- 🤖 **Lecture Augmentée par l'IA** :
  - **Traduction en Ligne** : Traductions contextuelles de haute qualité élégamment intégrées sous le texte original.
  - **Compagnon IA** : Un assistant IA en barre latérale prenant en charge le dialogue en streaming et la mémoire multi-tours.
  - **Large Compatibilité** : Prise en charge intégrée d'OpenAI, Anthropic, Gemini, DeepSeek, Grok, Alibaba Cloud Bailian, Volcengine, Tencent Hunyuan, MiniMax, Moonshot, SiliconFlow, Cerebras, SambaNova, Groq, Mistral, DeepInfra, Together AI, OpenRouter, Zhipu AI et ModelScope — 20 fournisseurs d'IA au total, plus des endpoints personnalisés compatibles OpenAI.

<div align="center">
  <img src="assets/reader_AItools.jpg" width="800" alt="AI Tools"><br>
  <sub>Barre de sélection · Traduction en ligne · Panneau latéral du compagnon IA</sub>
</div>

- 🔊 **Lecture TTS** : Propulsé par Edge-TTS avec plusieurs voix de haute qualité en chinois et en anglais.
- ✏️ **Surlignages et Notes** : Surlignage en 5 couleurs, annotations en ligne et signets — le tout stocké dans le **localStorage** de votre navigateur.

<div align="center">
  <img src="assets/reader_catelog.jpg" width="800" alt="Reading Layout"><br>
  <sub>Lecture en 3 colonnes : navigation ToC · Texte immersif · Surlignages multicolores</sub>
</div>

- 🎨 **Esthétique Minimaliste** : 6 thèmes sélectionnés et une mise en page flexible à 3 colonnes (ToC/Contenu/IA), optimisée pour tous les appareils.

<div align="center">
  <img src="assets/reader_setting.jpg" width="800" alt="Settings"><br>
  <sub>Thèmes, typographie, dictionnaires, modèles IA — configuration tout-en-un</sub>
</div>

## 🚀 Démarrage Rapide

Ce projet utilise [uv](https://docs.astral.sh/uv/) pour gérer l'environnement Python et les dépendances.

### 1. Installer uv
Assurez-vous que Python 3.10+ est disponible. Installez `uv` :
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Importer un Livre et Lancer
```bash
# Importer un livre EPUB
uv run reader3.py your_book.epub

# Démarrer le serveur
uv run server.py
```
Accédez au lecteur sur : 👉 **http://localhost:8123**

### 3. Configurer l'IA
Entrez dans l'interface de lecture, cliquez sur **Paramètres (Settings)** en haut à gauche et configurez votre **Fournisseur d'IA** et clé API (ex. [obtenez une clé Gemini gratuite](https://aistudio.google.com/apikey)).

> [!TIP]
> **🚀 Œuf de Pâques** : N'importe où sur la page, entrez **`↑ ↑ ↓ ↓ ← → ← → B A`** (Code Konami) pour déverrouiller le **Panneau de Routage IA Avancé** caché.

## 🛡️ Confidentialité
- **Local d'Abord** : Aucune donnée ne quitte votre appareil sauf si vous déclenchez explicitement une requête IA ou TTS.
- **Sans Compte** : Vos données restent exclusivement dans le `localStorage` de votre navigateur.

## 📚 Guide Utilisateur
Pour des configurations détaillées (dictionnaires hors ligne, accès multi-appareils, paramètres de port), consultez le [Guide Utilisateur](docs/GUIDE.md).

## 📄 Licence
[MIT License](LICENSE)
