[English](README.en.md) | [简体中文](README.md) | [繁體中文](README.zh-Hant.md) | [日本語](README.ja.md) | [한국어](README.ko.md) | Español | [Français](README.fr.md) | [Italiano](README.it.md)

# 🧊 Smoothie Reader (Reader3)

> "Cuando la tecnología es democratizada por la IA, la estética y el diseño centrado en el ser humano se convierten en los diferenciadores definitivos."

Inspirado por el [prototipo de lector minimalista](https://x.com/karpathy/status/1990577951671509438) de Andrej Karpathy, Smoothie Reader es un lector de libros electrónicos con IA que se ejecuta localmente. Integra búsqueda de palabras, traducción y diálogo con IA, lectura TTS y notas de resaltado, diseñado para una lectura profunda.

📖 **Libro de ejemplo incluido**: El repositorio incluye "Meditaciones" de Marco Aurelio (vía Project Gutenberg), listo para explorar tras clonar.

<div align="center">
  <img src="assets/library.jpg" width="800" alt="Library"><br>
  <sub>Tu biblioteca personal de un vistazo</sub>
</div>

## ✨ Características Principales

- 🔍 **Descubrimiento Intuitivo**: Resalte cualquier texto para revelar la barra de acciones. Soporte integrado para **ECDICT** (Inglés) y diccionarios chinos offline.
- 🤖 **Lectura Potenciada por IA**:
  - **Traducción en Línea**: Traducciones contextuales de alta calidad elegantemente incrustadas bajo el texto original.
  - **Compañero IA**: Un asistente de IA en la barra lateral que admite diálogos en streaming y memoria de múltiples turnos.
  - **Amplia Compatibilidad**: Soporte integrado para OpenAI, Anthropic, Gemini, DeepSeek, Grok, Alibaba Cloud Bailian, Volcengine, Tencent Hunyuan, MiniMax, Moonshot, SiliconFlow, Cerebras, SambaNova, Groq, Mistral, DeepInfra, Together AI, OpenRouter, Zhipu AI y ModelScope — 20 proveedores de IA en total, más endpoints personalizados compatibles con OpenAI.

<div align="center">
  <img src="assets/reader_AItools.jpg" width="800" alt="AI Tools"><br>
  <sub>Barra de selección · Traducción en línea · Panel lateral del compañero IA</sub>
</div>

- 🔊 **Lectura TTS**: Potenciado por Edge-TTS con múltiples voces de alta calidad en chino e inglés.
- ✏️ **Resaltados y Notas**: Resaltado de 5 colores, anotaciones en línea y marcadores — todo almacenado en el **localStorage** de tu navegador.

<div align="center">
  <img src="assets/reader_catelog.jpg" width="800" alt="Reading Layout"><br>
  <sub>Lectura en 3 columnas: navegación ToC · Texto inmersivo · Resaltados multicolor</sub>
</div>

- 🎨 **Estética Minimalista**: 6 temas curados y un diseño flexible de 3 columnas (ToC/Contenido/IA), optimizado para todos los dispositivos.

<div align="center">
  <img src="assets/reader_setting.jpg" width="800" alt="Settings"><br>
  <sub>Temas, tipografía, diccionarios, modelos IA — configuración todo en uno</sub>
</div>

## 🚀 Inicio Rápido

Este proyecto utiliza [uv](https://docs.astral.sh/uv/) para gestionar el entorno Python y las dependencias.

### 1. Instalar uv
Asegúrese de tener Python 3.10+ disponible. Instale `uv`:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Importar un Libro e Iniciar
```bash
# Importar un libro electrónico EPUB
uv run reader3.py your_book.epub

# Iniciar el servidor
uv run server.py
```
Acceda al lector en: 👉 **http://localhost:8123**

### 3. Configurar IA
Entre en la interfaz de lectura, haga clic en **Configuración (Settings)** en la esquina superior izquierda y configure su **Proveedor de IA** y clave API (ej., [obtenga una Gemini Key gratis](https://aistudio.google.com/apikey)).

> [!TIP]
> **🚀 Huevo de Pascua**: En cualquier lugar de la página, ingrese **`↑ ↑ ↓ ↓ ← → ← → B A`** (Código Konami) para desbloquear el **Panel Avanzado de Enrutamiento de IA** oculto.

## 🛡️ Privacidad
- **Local Primero**: Ningún dato sale de su dispositivo a menos que active explícitamente una solicitud de IA o TTS.
- **Sin Cuenta**: Sus datos se almacenan solo en el `localStorage` de su navegador.

## 📚 Guía de Usuario
Para configuraciones detalladas (diccionarios offline, acceso multidispositivo, configuración de puertos), consulte la [Guía de Usuario](docs/GUIDE.md).

## 📄 Licencia
[MIT License](LICENSE)
