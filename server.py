import asyncio
import hashlib
import json
import os
import pickle
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import zlib
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import edge_tts
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

# AI Imports
from google import genai as google_genai
from pydantic import BaseModel

from reader3 import Book, process_epub, save_to_pickle
import pdf_translation

# Keep bundled resources separate from writable user data in frozen builds.
# `dist/` is replaced on every PyInstaller build, so it must never hold books,
# caches, or API configuration.
RESOURCE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
EXE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else RESOURCE_DIR
if getattr(sys, "frozen", False):
    APP_DIR = os.path.join(os.getenv("LOCALAPPDATA") or EXE_DIR, "fixedpdf")
    os.makedirs(APP_DIR, exist_ok=True)
else:
    APP_DIR = RESOURCE_DIR

# Load .env file automatically
if getattr(sys, "frozen", False):
    load_dotenv(os.path.join(EXE_DIR, ".env"))
load_dotenv(os.path.join(APP_DIR, ".env"))

# --- AI 链路日志：记录每次 AI 请求/流式原始数据/清理后数据，用于排查 ---
import logging
_ai_logger = logging.getLogger('smoothie_ai')
_ai_logger.setLevel(logging.INFO)
if not _ai_logger.handlers:
    _AI_LOG_PATH = os.path.join(APP_DIR, 'server_ai.log')
    _fh = logging.FileHandler(_AI_LOG_PATH, encoding='utf-8')
    _fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    _ai_logger.addHandler(_fh)
    _ai_logger.propagate = False


def _ai_log(msg: str, *args):
    try:
        _ai_logger.info(msg, *args)
    except Exception:
        pass


# --- AI Provider System ---
AI_CONFIG_PATH = os.path.join(APP_DIR, 'ai_config.json')

_PROVIDER_DEFS = {
    'openai':      {'name': 'OpenAI',       'base_url': 'https://api.openai.com/v1/',                           'default_model': 'gpt-4o-mini',                    'format': 'openai'},
    'anthropic':   {'name': 'Anthropic',     'base_url': 'https://api.anthropic.com/v1/',                        'default_model': 'claude-sonnet-4-20250514',       'format': 'anthropic'},
    'gemini':      {'name': 'Google Gemini', 'base_url': '',                                                     'default_model': 'gemini-3-flash-preview',               'format': 'gemini'},
    'deepseek':    {'name': 'DeepSeek',      'base_url': 'https://api.deepseek.com/v1/',                         'default_model': 'deepseek-chat',                  'format': 'openai', 'vision_model': 'deepseek-v4-flash-vision-exp'},
    'grok':        {'name': 'Grok (xAI)',    'base_url': 'https://api.x.ai/v1/',                                 'default_model': 'grok-3-mini-fast',               'format': 'openai'},
    'dashscope':   {'name': '阿里云百炼',     'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1/',   'default_model': 'qwen-plus',                      'format': 'openai'},
    'volcengine':  {'name': '火山引擎',       'base_url': 'https://ark.cn-beijing.volces.com/api/v3/',            'default_model': 'doubao-1-5-pro-32k-250115',     'format': 'openai'},
    'hunyuan':     {'name': '腾讯混元',       'base_url': 'https://api.hunyuan.cloud.tencent.com/v1/',            'default_model': 'hunyuan-turbos-latest',          'format': 'openai'},
    'minimax':     {'name': 'MiniMax',       'base_url': 'https://api.minimax.io/v1/',                           'default_model': 'MiniMax-M2.5',                   'format': 'openai'},
    'moonshot':    {'name': '月之暗面',       'base_url': 'https://api.moonshot.cn/v1/',                          'default_model': 'moonshot-v1-8k',                 'format': 'openai'},
    'siliconflow': {'name': '硅基流动',       'base_url': 'https://api.siliconflow.cn/v1/',                       'default_model': 'Qwen/Qwen2.5-7B-Instruct',      'format': 'openai'},
    'cerebras':    {'name': 'Cerebras',      'base_url': 'https://api.cerebras.ai/v1/',                          'default_model': 'llama-3.3-70b',                  'format': 'openai'},
    'sambanova':   {'name': 'SambaNova',     'base_url': 'https://api.sambanova.ai/v1/',                         'default_model': 'Meta-Llama-3.3-70B-Instruct',   'format': 'openai'},
    'groq':        {'name': 'Groq',          'base_url': 'https://api.groq.com/openai/v1/',                      'default_model': 'llama-3.3-70b-versatile',        'format': 'openai'},
    'mistral':     {'name': 'Mistral',       'base_url': 'https://api.mistral.ai/v1/',                           'default_model': 'mistral-small-latest',           'format': 'openai'},
    'deepinfra':   {'name': 'DeepInfra',     'base_url': 'https://api.deepinfra.com/v1/openai/',                 'default_model': 'meta-llama/Llama-3.3-70B-Instruct', 'format': 'openai'},
    'together':    {'name': 'Together AI',   'base_url': 'https://api.together.xyz/v1/',                         'default_model': 'meta-llama/Llama-3.3-70B-Instruct-Turbo', 'format': 'openai'},
    'openrouter':  {'name': 'OpenRouter',    'base_url': 'https://openrouter.ai/api/v1/',                        'default_model': 'openai/gpt-4o-mini',             'format': 'openai'},
    'zhipuai':     {'name': '智谱AI',         'base_url': 'https://open.bigmodel.cn/api/paas/v4/',               'default_model': 'glm-4.7-flash',                  'format': 'openai'},
    'modelscope':  {'name': 'ModelScope',    'base_url': 'https://api-inference.modelscope.cn/v1/',             'default_model': 'Qwen/Qwen2.5-72B-Instruct',     'format': 'openai'},
    'ollama':      {'name': 'Ollama (本地)',  'base_url': 'http://localhost:11434/v1',                            'default_model': 'qwen2.5:7b',                     'format': 'openai'},
    'cli':         {'name': '本地 CLI (自动探测)', 'base_url': '',                                         'default_model': '',                               'format': 'cli'},
    'custom':      {'name': '自定义 (OpenAI 兼容)', 'base_url': '',                                              'default_model': '',                               'format': 'openai'},
}

_ai_config = {'providers': {}, 'order': []}

# 已知的本地 CLI 及其非交互调用方式。{prompt} 会被替换为实际提示词。
# 设置页只列出本机真正装了的那些，用户从下拉里挑一个即可，无需手写命令模板。
_KNOWN_CLIS = (
    {'id': 'cursor-agent', 'name': 'Cursor Agent', 'command': 'cursor-agent --print "{prompt}"'},
    {'id': 'claude', 'name': 'Claude Code', 'command': 'claude --print "{prompt}"'},
    {'id': 'codex', 'name': 'Codex CLI', 'command': 'codex exec "{prompt}"'},
    {'id': 'gemini', 'name': 'Gemini CLI', 'command': 'gemini -p "{prompt}"'},
    {'id': 'qwen', 'name': 'Qwen Code', 'command': 'qwen -p "{prompt}"'},
    {'id': 'opencode', 'name': 'OpenCode', 'command': 'opencode run "{prompt}"'},
    {'id': 'crush', 'name': 'Crush', 'command': 'crush run "{prompt}"'},
    {'id': 'goose', 'name': 'Goose', 'command': 'goose run -t "{prompt}"'},
    {'id': 'copilot', 'name': 'GitHub Copilot CLI', 'command': 'copilot -p "{prompt}"'},
    {'id': 'aider', 'name': 'Aider', 'command': 'aider --message "{prompt}" --yes'},
)


def _detect_local_clis() -> list[dict]:
    """探测本机已安装的 CLI，供设置页选择，免去手写命令模板。

    交给 ``shutil.which``：它按 ``PATHEXT`` 解析 Windows 上的 .cmd/.exe，比手动
    拼接路径可靠。未安装的条目不返回。
    """
    return [dict(entry) for entry in _KNOWN_CLIS if shutil.which(entry['id'])]


# --- Dictionary Management ---
_DICT_DIR = os.path.join(APP_DIR, 'dict')
_DICT_FILES = {
    'ecdict':  {'filename': 'stardict.db', 'label': 'ECDICT英文词典', 'label_en': 'ECDICT English', 'size_mb': 307, 'gz_mb': 134},
    'cn_dict': {'filename': 'cn_dict.db',  'label': '中文词典',       'label_en': 'Chinese Dict',    'size_mb': 48,  'gz_mb': 25},
}
_DEFAULT_DICT_URL = 'https://github.com/Golden0Voyager/reader3-dict/releases/download/dict-v1'


def _load_ai_config():
    """Load AI provider config from JSON file."""
    global _ai_config
    if os.path.exists(AI_CONFIG_PATH):
        try:
            with open(AI_CONFIG_PATH) as f:
                _ai_config = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    _ai_config.setdefault('providers', {})
    _ai_config.setdefault('order', [])


def _save_ai_config():
    """Save AI provider config to JSON file."""
    with open(AI_CONFIG_PATH, 'w') as f:
        json.dump(_ai_config, f, indent=2, ensure_ascii=False)


def _get_builtin_providers():
    """Return builtin provider configs from .env (in-memory only, never shown in UI)."""
    builtins = []
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        builtins.append(('gemini', gemini_key, 'gemini-3-flash-preview'))
    zhipu_key = os.getenv("ZHIPUAI_API_KEY")
    if zhipu_key:
        builtins.append(('zhipuai', zhipu_key, 'glm-4.7-flash'))
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")
    if deepseek_key:
        builtins.append(('deepseek', deepseek_key, 'deepseek-chat'))
    return builtins


# Set of provider IDs that have builtin .env keys
_BUILTIN_IDS = {pid for pid, _, _ in _get_builtin_providers()}


def _get_enabled_providers():
    """Return list of enabled provider configs in priority order.
    User-configured providers first, then builtin (.env) providers as fallback."""
    result = []
    seen = set()
    def _make_entry(pid, p):
        defn = _PROVIDER_DEFS.get(pid, {})
        if not defn and pid.startswith('custom'):
            defn = _PROVIDER_DEFS.get('custom', {})
        name = p.get('custom_name') or defn.get('name', pid)
        default_model = defn.get('default_model', '')
        entry = {
            'id': pid, 'name': name,
            'api_key': p['api_key'],
            'model': p.get('model') or default_model,
            'base_url': p.get('base_url') or defn.get('base_url', ''),
            'format': defn.get('format', 'openai'),
            'default_model': default_model,
            'vision_model': p.get('vision_model', ''),
            'default_vision_model': defn.get('vision_model', ''),
            'cli_command': p.get('cli_command', ''),
        }
        if p.get('temperature') is not None:
            entry['temperature'] = p['temperature']
        if p.get('max_tokens') is not None:
            entry['max_tokens'] = p['max_tokens']
        return entry
    # 1) User-configured providers (from ai_config.json)
    for pid in _ai_config.get('order', []):
        p = _ai_config['providers'].get(pid)
        if p and p.get('enabled') and (p.get('api_key') or pid in ('ollama', 'cli')):
            result.append(_make_entry(pid, p))
            seen.add(pid)
    for pid, p in _ai_config['providers'].items():
        if pid not in seen and p.get('enabled') and (p.get('api_key') or pid in ('ollama', 'cli')):
            result.append(_make_entry(pid, p))
            seen.add(pid)
    # 2) Builtin providers from .env as fallback (skip if user already configured same provider)
    for pid, bkey, bmodel in _get_builtin_providers():
        if pid not in seen:
            defn = _PROVIDER_DEFS.get(pid, {})
            result.append({
                'id': pid, 'name': defn.get('name', pid) + ' (内置)',
                'api_key': bkey,
                'model': bmodel,
                'base_url': defn.get('base_url', ''),
                'format': defn.get('format', 'openai'),
                'vision_model': '',
                'default_model': defn.get('default_model', bmodel),
                'default_vision_model': defn.get('vision_model', ''),
            })
    return result


def _pick_model(p: dict, images=None) -> str:
    """选择实际使用的模型：
    - 有图片：vision_model（用户配置的或该服务商的默认视觉模型）→ model → default_model
    - 无图片：用 model → default_model，尊重用户选择

    vision_model 允许为空：部分服务商的默认模型不支持图片，回退到它只会拿到
    「不支持图片识别」的报错。因此优先用服务商自带的视觉默认值。
    """
    if images:
        return (p.get('vision_model') or p.get('default_vision_model')
                or p.get('model') or p.get('default_model', ''))
    return p.get('model') or p.get('default_model', '')


# Initialize provider config on module load
_load_ai_config()
_enabled = _get_enabled_providers()
if _enabled:
    print(f"AI providers: {', '.join(p['name'] + ' (' + p['model'] + ')' for p in _enabled)}")
else:
    print("Warning: No AI providers configured. Add one in Settings or set API keys in .env")

# Google Translate direct API (fast, connection-pooled, independent of AI providers)
_gt_client = httpx.AsyncClient(timeout=5, http2=False, headers={"User-Agent": "FixedPDF/1.0"})

# Shared httpx pool for AI provider calls (reuse TCP/TLS connections)
_ai_client = httpx.AsyncClient(timeout=300, trust_env=True, headers={"User-Agent": "FixedPDF/1.0"})


# --- Unified AI Dispatch ---

def _build_user_content(prompt, images=None):
    """构造 OpenAI 兼容的用户消息 content。有图片时返回多模态数组，否则返回纯字符串。"""
    if not images:
        return prompt
    content = []
    for img in images:
        # img 形如 "data:image/png;base64,xxxx" 或纯 http(s) URL
        content.append({"type": "image_url", "image_url": {"url": img}})
    content.append({"type": "text", "text": prompt})
    return content


async def _call_openai_compat(base_url, api_key, model, prompt, temperature, max_tokens, extra_body=None, images=None,
                              final_only=False):
    """Non-streaming call to OpenAI-compatible chat/completions endpoint."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "model": model,
        "messages": [{"role": "user", "content": _build_user_content(prompt, images)}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra_body:
        body.update(extra_body)
    resp = await _ai_client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=body)
    if resp.status_code != 200:
        try:
            err = resp.json().get('error', {})
            detail = err.get('message', '') if isinstance(err, dict) else str(err)
        except Exception:
            detail = resp.text[:200]
        raise Exception(f"HTTP {resp.status_code}: {detail}")
    msg = resp.json()["choices"][0]["message"]
    content = msg.get("content") or ""
    if final_only and not content:
        raise ValueError('翻译服务没有返回最终译文，可能已耗尽输出预算；不会使用推理文本替代译文。')
    # 推理模型（如 deepseek-reasoner / vision 变体）可能把内容输出在 reasoning_content，
    # 而 content 为空（思考过程把 max_tokens 吃光）。此时回退到 reasoning_content，避免空白。
    if not content:
        content = msg.get("reasoning_content") or ""
    return content


async def _call_anthropic(base_url, api_key, model, prompt, temperature, max_tokens):
    """Non-streaming call to Anthropic Messages API."""
    resp = await _ai_client.post(
        f"{base_url.rstrip('/')}/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}], "temperature": temperature},
    )
    if resp.status_code != 200:
        try:
            err = resp.json().get('error', {})
            detail = err.get('message', '') if isinstance(err, dict) else str(err)
        except Exception:
            detail = resp.text[:200]
        raise Exception(f"HTTP {resp.status_code}: {detail}")
    return resp.json()["content"][0]["text"]


async def _call_gemini(api_key, model_name, prompt, temperature, max_tokens):
    """Non-streaming call to Gemini via SDK."""
    client = google_genai.Client(api_key=api_key)
    config = google_genai.types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens)
    response = await asyncio.to_thread(lambda: client.models.generate_content(model=model_name, contents=prompt, config=config))
    return response.text.strip()


async def _call_cli(cli_command: str, prompt: str, timeout: int = 600) -> str:
    """通过本地 CLI（如 cursor-agent、claude）执行 prompt。

    cli_command 来自 ``_KNOWN_CLIS``，已带好各自的非交互参数；``{prompt}`` 会被
    替换为实际 prompt。用户也可以在设置里改写这个模板。
    """
    if not cli_command:
        raise Exception("未配置 CLI 命令模板")
    # 用 shell 执行（Windows 用 cmd，POSIX 用 sh）
    import sys
    cmd = cli_command.replace('{prompt}', prompt)
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise Exception("CLI 执行超时（>600s）")
    out = stdout.decode('utf-8', errors='replace').strip()
    if proc.returncode != 0:
        err = stderr.decode('utf-8', errors='replace').strip()
        raise Exception(f"CLI 退出码 {proc.returncode}: {err[:300] or out[:300]}")
    return out


async def _ai_complete(prompt, temperature=0.7, max_tokens=4096, task=None, images=None, provider_id=None):
    """Unified non-streaming AI call. Returns (text, display_name). Tries providers in order with fallback."""
    providers = _get_enabled_providers()
    if not providers:
        raise HTTPException(status_code=500, detail="AI not configured — please add a provider in Settings")
    # 显式指定 provider 时优先（用户在下拉框选择模型）
    if provider_id:
        routed = [p for p in providers if p['id'] == provider_id]
        others = [p for p in providers if p['id'] != provider_id]
        providers = routed + others
    # Task-specific provider routing
    routing = _ai_config.get('task_routing', {})
    routed_pid = routing.get(task) if task else None
    if routed_pid:
        routed = [p for p in providers if p['id'] == routed_pid]
        others = [p for p in providers if p['id'] != routed_pid]
        providers = routed + others
    last_error = None
    for p in providers:
        try:
            t = p.get('temperature', temperature)
            mt = p.get('max_tokens', max_tokens)
            fmt = p['format']
            if images and fmt in ('gemini', 'anthropic', 'cli'):
                # 这些 provider 暂未实现多模态图片，跳过
                continue
            model = _pick_model(p, images)
            if fmt == 'gemini':
                text = await _call_gemini(p['api_key'], model, prompt, t, mt)
            elif fmt == 'anthropic':
                text = await _call_anthropic(p['base_url'], p['api_key'], model, prompt, t, mt)
            elif fmt == 'cli':
                text = await _call_cli(p.get('cli_command', ''), prompt)
            else:
                disable_thinking = p['id'] == 'zhipuai' or (p['id'] == 'deepseek' and task == 'translate')
                extra = {"thinking": {"type": "disabled"}} if disable_thinking else None
                text = await _call_openai_compat(p['base_url'], p['api_key'], model, prompt, t, mt, extra_body=extra,
                                                 images=images, final_only=task == 'translate')
            return text.strip(), f"{p['name']} {model or 'cli'}"
        except Exception as e:
            last_error = e
            print(f"[AI] {p['name']} failed: {e}")
            continue
    raise HTTPException(status_code=500, detail=f"All AI providers failed. Last error: {last_error}")


async def _stream_openai_compat(base_url, api_key, model, prompt, temperature, max_tokens, extra_body=None, images=None):
    """Streaming async generator for OpenAI-compatible endpoint."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {"model": model, "messages": [{"role": "user", "content": _build_user_content(prompt, images)}], "stream": True, "temperature": temperature, "max_tokens": max_tokens}
    if extra_body:
        body.update(extra_body)
    async with httpx.AsyncClient(timeout=60, trust_env=True, headers={"User-Agent": "FixedPDF/1.0"}) as client:
        async with client.stream("POST", f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=body) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                raise Exception(f"HTTP {resp.status_code}: {err[:300].decode(errors='replace')}")
            buf = b''
            async for raw in resp.aiter_bytes():
                buf += raw
                while b'\n' in buf:
                    line_bytes, buf = buf.split(b'\n', 1)
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                        content = chunk["choices"][0]["delta"].get("content", "")
                        if content:
                            yield content
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


async def _stream_anthropic(base_url, api_key, model, prompt, temperature, max_tokens):
    """Streaming async generator for Anthropic Messages API."""
    async with httpx.AsyncClient(timeout=60, trust_env=True, headers={"User-Agent": "FixedPDF/1.0"}) as client:
        async with client.stream("POST", f"{base_url.rstrip('/')}/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}], "temperature": temperature, "stream": True},
        ) as resp:
            if resp.status_code != 200:
                err = await resp.aread()
                raise Exception(f"HTTP {resp.status_code}: {err[:300].decode(errors='replace')}")
            buf = b''
            async for raw in resp.aiter_bytes():
                buf += raw
                while b'\n' in buf:
                    line_bytes, buf = buf.split(b'\n', 1)
                    line = line_bytes.decode('utf-8', errors='replace').strip()
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                        if event.get("type") == "content_block_delta":
                            text = event.get("delta", {}).get("text", "")
                            if text:
                                yield text
                    except (json.JSONDecodeError, KeyError):
                        continue


# --- Stream HTML sanitizer: strip/convert raw HTML tags emitted by LLMs ---
import re as _re_html

_HTML_CLEAN_RULES = [
    (_re_html.compile(r'<!--.*?-->', _re_html.S), ''),
    (_re_html.compile(r'<br\s*/?>', _re_html.I), '\n'),
    (_re_html.compile(r'</(p|div|li|ul|ol|h[1-6])>', _re_html.I), '\n'),
    (_re_html.compile(r'<(p|div|ul|ol)[^>]*>', _re_html.I), '\n'),
    (_re_html.compile(r'<li[^>]*>', _re_html.I), '- '),
    (_re_html.compile(r'<h([1-6])[^>]*>', _re_html.I), lambda m: '#' * int(m.group(1)) + ' '),
    (_re_html.compile(r'<strong[^>]*>(.*?)</strong>', _re_html.I | _re_html.S), r'**\1**'),
    (_re_html.compile(r'<b[^>]*>(.*?)</b>', _re_html.I | _re_html.S), r'**\1**'),
    (_re_html.compile(r'<em[^>]*>(.*?)</em>', _re_html.I | _re_html.S), r'*\1*'),
    (_re_html.compile(r'<i[^>]*>(.*?)</i>', _re_html.I | _re_html.S), r'*\1*'),
    (_re_html.compile(r'<code[^>]*>(.*?)</code>', _re_html.I | _re_html.S), r'`\1`'),
    (_re_html.compile(r'<[^>]+>', _re_html.S), ''),
]


def _sanitize_html(text: str) -> str:
    """Convert raw HTML to markdown-ish plain text."""
    if not text:
        return text
    for pattern, repl in _HTML_CLEAN_RULES:
        text = pattern.sub(repl, text)
    return text


class _StreamSanitizer:
    """Buffer streamed text so HTML tags spanning chunks are handled atomically."""

    def __init__(self):
        self._buf = ''

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        idx = self._buf.rfind('<')
        if idx == -1:
            out, self._buf = self._buf, ''
        else:
            out, self._buf = self._buf[:idx], self._buf[idx:]
        return _sanitize_html(out)

    def flush(self) -> str:
        out, self._buf = self._buf, ''
        return _sanitize_html(out)


async def _sanitized_stream(agen):
    """Wrap an async generator, sanitizing HTML across chunk boundaries."""
    s = _StreamSanitizer()
    raw_chunks = []
    clean_chunks = []
    async for chunk in agen:
        raw_chunks.append(chunk)
        cleaned = s.feed(chunk)
        clean_chunks.append(cleaned)
        if cleaned:
            yield cleaned
    tail = s.flush()
    clean_chunks.append(tail)
    if tail:
        yield tail
    _ai_log("STREAM-RAW: %r", ''.join(raw_chunks))
    _ai_log("STREAM-CLEAN: %r", ''.join(clean_chunks))


async def _ai_stream(prompt, temperature=0.7, max_tokens=4096, task=None, images=None, provider_id=None):
    """Unified streaming AI. Returns async generator with auto-fallback between providers."""
    providers = _get_enabled_providers()
    # 显式指定 provider 时优先
    if provider_id:
        routed = [p for p in providers if p['id'] == provider_id]
        others = [p for p in providers if p['id'] != provider_id]
        providers = routed + others
    # Task-specific provider routing
    routing = _ai_config.get('task_routing', {})
    routed_pid = routing.get(task) if task else None
    if routed_pid:
        routed = [p for p in providers if p['id'] == routed_pid]
        others = [p for p in providers if p['id'] != routed_pid]
        providers = routed + others

    async def generate():
        if not providers:
            yield "[Error: AI not configured — please add a provider in Settings]"
            return
        for i, p in enumerate(providers):
            try:
                t = p.get('temperature', temperature)
                mt = p.get('max_tokens', max_tokens)
                fmt = p['format']
                if images and fmt in ('gemini', 'anthropic', 'cli'):
                    # 这些 provider 暂未实现多模态图片，跳过
                    continue
                model = _pick_model(p, images)
                if fmt == 'gemini':
                    client = google_genai.Client(api_key=p['api_key'])
                    config = google_genai.types.GenerateContentConfig(temperature=t)
                    response = await asyncio.to_thread(
                        lambda: client.models.generate_content_stream(model=model, contents=prompt, config=config)
                    )
                    for chunk in response:
                        try:
                            if chunk.text:
                                yield chunk.text
                        except (ValueError, AttributeError):
                            continue
                elif fmt == 'anthropic':
                    async for chunk in _stream_anthropic(p['base_url'], p['api_key'], model, prompt, t, mt):
                        yield chunk
                elif fmt == 'cli':
                    # CLI 不支持流式，一次性拿到完整结果再输出
                    text = await _call_cli(p.get('cli_command', ''), prompt)
                    if text:
                        yield text
                else:
                    extra = {"thinking": {"type": "disabled"}} if p['id'] == 'zhipuai' else None
                    async for chunk in _stream_openai_compat(p['base_url'], p['api_key'], model, prompt, t, mt, extra_body=extra, images=images):
                        yield chunk
                yield f"\n<!--model:{p['name']} {model or 'cli'}-->"
                return  # Success
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"[AI stream] {p['name']} failed: {e}")
                if i == len(providers) - 1:
                    if images:
                        yield "\n[提示：当前配置的服务商/模型不支持图片识别。请在设置中为该服务商填写「视觉模型」（支持多模态/vision 的模型名），或改用支持图片的服务商。]"
                    else:
                        yield f"\n[Error: {e}]"
                continue

    return generate()

def _detect_cjk_ratio(text):
    cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
    return cjk / max(len(text), 1)

_cn_dict_cache: dict[str, str] = {}

async def _chinese_define(word: str) -> str | None:
    """AI-powered Chinese word definition, with in-memory cache."""
    if word in _cn_dict_cache:
        return _cn_dict_cache[word]
    prompt = f'请用一句话简明解释"{word}"的含义，像词典释义一样简短。只输出释义，不要引号不要前缀。'
    try:
        result, _ = await _ai_complete(prompt, temperature=0.1, max_tokens=200, task='dict')
        _cn_dict_cache[word] = result
        return result
    except Exception:
        return None

async def _google_translate(text, dest='zh-CN'):
    """Direct Google Translate API call, ~100ms with connection reuse."""
    resp = await _gt_client.get('https://translate.googleapis.com/translate_a/single', params={
        'client': 'gtx', 'sl': 'auto', 'tl': dest, 'dt': 't', 'q': text
    })
    data = resp.json()
    return ''.join(s[0] for s in data[0] if s[0])

def _open_dict_db(path):
    """Open a dict SQLite DB with read-optimized settings."""
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA mmap_size=67108864')  # 64MB mmap for faster reads
    conn.execute('PRAGMA cache_size=-8000')     # 8MB page cache
    return conn

# ECDICT offline dictionary (~3.4M entries, <1ms lookup)
_dict_db_path = os.path.join(os.path.dirname(__file__), 'dict', 'stardict.db')
_dict_conn = None
if os.path.exists(_dict_db_path):
    _dict_conn = _open_dict_db(_dict_db_path)

# Chinese dictionary (457K entries: xinhua + moedict, <1ms lookup)
_cn_dict_path = os.path.join(os.path.dirname(__file__), 'dict', 'cn_dict.db')
_cn_dict_conn = None
if os.path.exists(_cn_dict_path):
    _cn_dict_conn = _open_dict_db(_cn_dict_path)

def _reload_dict():
    """Hot-reload dictionary connections after download."""
    global _dict_conn, _cn_dict_conn
    for path, conn_name in [(_dict_db_path, '_dict_conn'), (_cn_dict_path, '_cn_dict_conn')]:
        if os.path.exists(path) and globals()[conn_name] is None:
            globals()[conn_name] = _open_dict_db(path)

def _dict_lookup(word: str) -> dict | None:
    """Look up a word in the local ECDICT dictionary. Returns dict or None."""
    if not _dict_conn:
        return None
    row = _dict_conn.execute(
        'SELECT word, phonetic, translation, definition FROM dict WHERE word = ? COLLATE NOCASE',
        (word.strip(),)
    ).fetchone()
    if not row or not (row['translation'] or row['definition']):
        return None
    return {
        'word': row['word'],
        'phonetic': row['phonetic'] or '',
        'translation': (row['translation'] or '').strip(),
        'definition': (row['definition'] or '').strip(),
    }

def _cn_dict_lookup(word: str) -> dict | None:
    """Look up a Chinese word in local cn_dict. Returns dict or None."""
    if not _cn_dict_conn:
        return None
    row = _cn_dict_conn.execute(
        'SELECT word, pinyin, definition, source FROM cn_dict WHERE word = ?',
        (word.strip(),)
    ).fetchone()
    if not row or not row['definition']:
        return None
    return {
        'word': row['word'],
        'pinyin': row['pinyin'] or '',
        'definition': row['definition'].strip(),
        'source': row['source'],
    }

async def _wiki_summary(term: str) -> dict:
    """Fetch Wikipedia summary for a term. Auto-detect language."""
    import urllib.parse
    import urllib.request
    is_cjk = _detect_cjk_ratio(term) > 0.3
    lang = 'zh' if is_cjk else 'en'
    try:
        encoded = urllib.parse.quote(term)
        url = f'https://{lang}.wikipedia.org/api/rest_v1/page/summary/{encoded}'
        req = urllib.request.Request(url, headers={'User-Agent': 'FixedPDF/1.0'})
        def _fetch():
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read())
        data = await asyncio.to_thread(_fetch)
        return {
            'title': data.get('title', ''),
            'extract': data.get('extract', ''),
            'url': data.get('content_urls', {}).get('desktop', {}).get('page', ''),
        }
    except Exception:
        return {}

import re as _re


def _safe_dirname(title: str, authors: list[str] = None) -> str:
    """Sanitize book title + author for use as directory name."""
    name = _re.sub(r'[\\/:*?"<>|]', '', title).strip()
    name = _re.sub(r'\s+', ' ', name)
    if authors and authors[0]:
        author = _re.sub(r'[\\/:*?"<>|]', '', authors[0]).strip()
        if author:
            name = f"{name} - {author}"
    if len(name) > 80:
        name = name[:80].rstrip()
    return name or 'untitled'


def _process_pdf(pdf_path: str, out_dir: str) -> dict:
    """Process a PDF file: extract metadata, render cover from first page, copy PDF."""
    import shutil

    import fitz  # PyMuPDF

    os.makedirs(out_dir, exist_ok=True)
    images_dir = os.path.join(out_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    meta = doc.metadata or {}
    title = meta.get("title", "").strip() or os.path.splitext(os.path.basename(pdf_path))[0]
    author = meta.get("author", "").strip()
    page_count = len(doc)

    # Render first page as cover
    if page_count > 0:
        page = doc[0]
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 2x zoom for quality
        cover_path = os.path.join(images_dir, "cover.png")
        pix.save(cover_path)
        with open(os.path.join(out_dir, "cover_image.txt"), "w") as f:
            f.write("cover.png")

    # 提取 PDF 目录（outline/bookmarks）
    toc = doc.get_toc()  # PyMuPDF 返回 [[level, title, page], ...]
    outline = [{"level": item[0], "title": item[1], "page": item[2]} for item in toc]

    doc.close()

    # Copy PDF to output dir
    dest_pdf = os.path.join(out_dir, "book.pdf")
    if os.path.abspath(pdf_path) != os.path.abspath(dest_pdf):
        shutil.copy2(pdf_path, dest_pdf)

    # Write meta.json
    meta_info = {
        "title": title,
        "author": author,
        "pages": page_count,
        "format": "pdf",
        "outline": outline,
    }
    with open(os.path.join(out_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta_info, f, ensure_ascii=False)

    return meta_info


app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)  # gzip responses > 1KB
templates = Jinja2Templates(directory=os.path.join(RESOURCE_DIR, "templates"))

# Where are the book folders located?
BOOKS_DIR = os.path.join(APP_DIR, "books")

# TTS audio cache directory
TTS_CACHE_DIR = os.path.join(BOOKS_DIR, ".tts_cache")
os.makedirs(TTS_CACHE_DIR, exist_ok=True)

# server-cache-lru: Multi-level cache for AI Analysis
# We use both in-memory and could easily extend to disk.
_analysis_cache = {}

def _get_text_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()

@lru_cache(maxsize=20)
def load_book_cached(folder_name: str) -> Book | None:
    """Load a Book object from its pickle file, with LRU caching."""
    file_path = os.path.join(BOOKS_DIR, folder_name, "book.pkl")
    if not os.path.exists(file_path):
        return None
    try:
        with open(file_path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None

# --- Library metadata index (avoid full pickle load for listing) ---
_LIBRARY_INDEX = os.path.join(BOOKS_DIR, ".library_index.json")

def _build_library_index():
    """Scan books dir, build/update lightweight metadata index."""
    index = {}
    if os.path.exists(_LIBRARY_INDEX):
        try:
            with open(_LIBRARY_INDEX) as f:
                index = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass
    changed = False
    current_dirs = set()
    if not os.path.exists(BOOKS_DIR):
        return index
    for item in os.listdir(BOOKS_DIR):
        if not item.endswith("_data") or not os.path.isdir(os.path.join(BOOKS_DIR, item)):
            continue
        current_dirs.add(item)
        # Check for PDF (meta.json) or EPUB (book.pkl)
        meta_json_path = os.path.join(BOOKS_DIR, item, "meta.json")
        pkl_path = os.path.join(BOOKS_DIR, item, "book.pkl")
        if os.path.exists(meta_json_path):
            # PDF book
            meta_mtime = os.path.getmtime(meta_json_path)
            if item in index and index[item].get('_mtime') == meta_mtime:
                continue
            try:
                with open(meta_json_path, encoding='utf-8') as f:
                    pdf_meta = json.load(f)
                old_display_title = index.get(item, {}).get('display_title')
                index[item] = {
                    'title': pdf_meta.get('title', 'Untitled'),
                    'author': pdf_meta.get('author', ''),
                    'chapters': pdf_meta.get('pages', 0),
                    'language': 'en',
                    'format': 'pdf',
                    '_mtime': meta_mtime,
                }
                if old_display_title:
                    index[item]['display_title'] = old_display_title
                changed = True
            except (OSError, json.JSONDecodeError):
                pass
        elif os.path.exists(pkl_path):
            # EPUB book
            pkl_mtime = os.path.getmtime(pkl_path)
            if item in index and index[item].get('_mtime') == pkl_mtime:
                continue
            book = load_book_cached(item)
            if book:
                old_display_title = index.get(item, {}).get('display_title')
                index[item] = {
                    'title': book.metadata.title,
                    'author': ', '.join(book.metadata.authors) if book.metadata.authors else '',
                    'chapters': len(book.spine),
                    'language': book.metadata.language or 'en',
                    'format': 'epub',
                    '_mtime': pkl_mtime,
                }
                if old_display_title:
                    index[item]['display_title'] = old_display_title
                changed = True
    # Remove deleted books from index
    for key in list(index.keys()):
        if key not in current_dirs:
            del index[key]
            changed = True
    if changed:
        with open(_LIBRARY_INDEX, 'w') as f:
            json.dump(index, f, ensure_ascii=False)
    return index

@app.get("/", response_class=HTMLResponse)
async def library_view(request: Request):
    index = await asyncio.to_thread(_build_library_index)
    books = []
    for item in sorted(index.keys()):
        meta = index[item]
        books.append({
            "id": item,
            "title": meta.get('display_title') or meta['title'],
            "original_title": meta['title'],
            "author": meta['author'],
            "chapters": meta['chapters'],
            "language": meta['language'],
            "format": meta.get('format', 'epub'),
            "mtime": meta.get('_mtime', 0),
        })
    return templates.TemplateResponse("library.html", {"request": request, "books": books})


def _find_cover_image(book_id: str) -> str | None:
    """Find cover image path for a book. Returns absolute path or None."""
    import re
    images_dir = os.path.join(BOOKS_DIR, book_id, "images")
    if not os.path.isdir(images_dir):
        return None

    img_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
    images = [f for f in os.listdir(images_dir) if f.lower().endswith(img_exts)]

    # 1. Marker file left by process_epub (most reliable)
    marker = os.path.join(BOOKS_DIR, book_id, "cover_image.txt")
    if os.path.exists(marker):
        with open(marker) as f:
            fname = f.read().strip()
        path = os.path.join(images_dir, fname)
        if os.path.exists(path):
            return path

    # 2. File named cover* (most explicit naming convention)
    for f in images:
        if re.match(r'cover', f, re.I):
            return os.path.join(images_dir, f)
    # 3. File containing *cover* anywhere in name
    for f in images:
        if 'cover' in f.lower():
            return os.path.join(images_dir, f)

    # 4. Parse first chapter HTML for image reference (often the cover page)
    book = load_book_cached(book_id)
    if book and book.spine:
        content = book.spine[0].content[:2000]
        m = re.search(r'(?:src|href)=["\']([^"\']+\.(?:jpe?g|png|gif|webp))', content, re.I)
        if m:
            src = m.group(1)
            fname = os.path.basename(src)
            path = os.path.join(images_dir, fname)
            if os.path.exists(path):
                return path

    # 5. Fallback: pick the largest image file (covers are usually the biggest)
    if images:
        largest = max(images, key=lambda f: os.path.getsize(os.path.join(images_dir, f)))
        return os.path.join(images_dir, largest)

    return None


@app.get("/api/book-cover/{book_id}")
async def serve_book_cover(book_id: str):
    """Serve cover image for an imported book."""
    safe_id = os.path.basename(book_id)
    cover = _find_cover_image(safe_id)
    if cover and os.path.exists(cover):
        return FileResponse(cover, headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="No cover found")

@app.get("/read/{book_id}/{chapter_index}", response_class=HTMLResponse)
async def read_chapter(request: Request, book_id: str, chapter_index: str):
    """Render a single chapter, or serve an image if chapter_index is a filename."""
    # Handle ../images/ or ../Images/ relative paths (book_id would be "images" or "Images")
    if book_id.lower() == 'images':
        referer = request.headers.get("referer", "")
        import re as _re
        from urllib.parse import unquote
        m = _re.search(r'/read/([^/]+)/', referer)
        if m:
            real_book_id = unquote(m.group(1))
            safe_name = os.path.basename(chapter_index)
            image_path = os.path.join(BOOKS_DIR, real_book_id, "images", safe_name)
            if os.path.exists(image_path):
                return FileResponse(image_path)
        raise HTTPException(status_code=404, detail="Image not found")

    # If it looks like a file (has extension), serve as image fallback
    if '.' in chapter_index:
        safe_name = os.path.basename(chapter_index)
        image_path = os.path.join(BOOKS_DIR, book_id, "images", safe_name)
        if os.path.exists(image_path):
            return FileResponse(image_path)
        raise HTTPException(status_code=404, detail="Not found")

    try:
        idx = int(chapter_index)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")

    book = load_book_cached(book_id)
    if not book or idx < 0 or idx >= len(book.spine):
        raise HTTPException(status_code=404, detail="Not found")

    current_chapter = book.spine[idx]
    prev_idx = idx - 1 if idx > 0 else None
    next_idx = idx + 1 if idx < len(book.spine) - 1 else None

    # Fix SVG cover distortion: replace preserveAspectRatio="none" and width/height="100%"
    import re as _re
    content = current_chapter.content

    # Normalize image paths: EPUB/images/x.jpg, OEBPS/Images/x.jpg, ../images/x.jpg → images/x.jpg
    content = _re.sub(r'(?:(?:\.\.\/)*(?:EPUB|OEBPS|OPS)\/|(?:\.\.\/)+)[Ii]mages/', 'images/', content)

    if '<svg' in content:
        content = _re.sub(r'preserveaspectratio="none"', 'preserveAspectRatio="xMidYMid meet"', content, flags=_re.I)
        content = _re.sub(r'(<svg[^>]*)\s+width="100%"', r'\1', content, flags=_re.I)
        content = _re.sub(r'(<svg[^>]*)\s+height="100%"', r'\1', content, flags=_re.I)

    return templates.TemplateResponse("reader.html", {
        "request": request, "book": book, "current_chapter": current_chapter,
        "chapter_index": idx, "book_id": book_id,
        "prev_idx": prev_idx, "next_idx": next_idx,
        "chapter_content": content
    })


@app.get("/read/{book_id}/images/{image_name}")
async def serve_book_image(book_id: str, image_name: str):
    """Serve an image file from a book's extracted images directory."""
    safe_name = os.path.basename(image_name)
    image_path = os.path.join(BOOKS_DIR, book_id, "images", safe_name)
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image_path)


# --- Rename book ---
@app.post("/api/rename-book/{book_id}")
async def rename_book(book_id: str, request: Request):
    """Set display_title for a book. Empty string removes custom title."""
    req = await request.json()
    title = req.get("title", "").strip()
    index = {}
    if os.path.exists(_LIBRARY_INDEX):
        with open(_LIBRARY_INDEX) as f:
            index = json.load(f)
    if book_id not in index:
        raise HTTPException(status_code=404, detail="Book not found")
    if title:
        index[book_id]['display_title'] = title
    else:
        index[book_id].pop('display_title', None)
    with open(_LIBRARY_INDEX, 'w') as f:
        json.dump(index, f, ensure_ascii=False)
    return {"ok": True, "display_title": title or None}


# --- Delete books ---
@app.post("/api/delete-books")
async def delete_books(req: dict):
    """Delete one or more books by their IDs."""
    import shutil
    book_ids = req.get("book_ids", [])
    if not book_ids:
        raise HTTPException(status_code=400, detail="No books specified")
    deleted = []
    for bid in book_ids:
        safe_id = os.path.basename(bid)
        book_dir = os.path.join(BOOKS_DIR, safe_id)
        if os.path.isdir(book_dir) and (
            os.path.exists(os.path.join(book_dir, "book.pkl")) or
            os.path.exists(os.path.join(book_dir, "book.pdf"))
        ):
            await asyncio.to_thread(shutil.rmtree, book_dir)
            deleted.append(safe_id)
    load_book_cached.cache_clear()
    return {"deleted": deleted, "count": len(deleted)}

# --- AI MODULE REFACTORED (Gemini 3 Pro standards) ---

class AIAnalyzeRequest(BaseModel):
    book_id: str
    chapter_index: int

@app.post("/api/ai/analyze")
async def analyze_chapter(req: AIAnalyzeRequest):
    """Analyze a chapter and return structured insights."""
    book = load_book_cached(req.book_id)
    if not book or req.chapter_index < 0 or req.chapter_index >= len(book.spine):
        raise HTTPException(status_code=404, detail="Chapter not found")
    chapter = book.spine[req.chapter_index]

    # Use text field, fallback to stripping HTML from content
    chapter_text = chapter.text.strip()
    if not chapter_text and chapter.content:
        from html.parser import HTMLParser
        class _Strip(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
            def handle_data(self, d):
                self.parts.append(d)
        s = _Strip()
        s.feed(chapter.content)
        chapter_text = ' '.join(s.parts).strip()

    if len(chapter_text) < 20:
        return {
            "summary": "本章内容过短，无法进行有效分析。",
            "key_points": [],
            "difficulties": "",
            "insight": ""
        }

    # server-cache-lru: Fingerprint based on text content hash
    content_hash = _get_text_hash(chapter_text)
    cache_key = f"{req.book_id}:{req.chapter_index}:{content_hash}"

    if cache_key in _analysis_cache:
        return _analysis_cache[cache_key]

    prompt = f"""你是一位经验丰富的读书会领读者，同时具备深厚的文学素养和跨学科知识。
你正在带领一群认真的成年读者讨论这本书。你的风格：有见地但不卖弄，善于发现文字背后的深意。

书名：{book.metadata.title}
作者：{', '.join(book.metadata.authors) if book.metadata.authors else '未知'}
章节：{chapter.title}

【本章内容】：
{chapter_text[:15000]}

请阅读后，以领读者的身份进行分析。严格按以下 JSON 返回（不要包含 ```json 标记）：

{{
    "summary": "用 150-250 字概述本章核心内容。不要罗列事件，而是说清楚：这一章到底在讲什么、推进了什么、改变了什么。如果是非虚构类，提炼核心论点和关键论据。",
    "key_points": [
        "提炼 3-5 个本章最值得关注的要点。每个要点用一句话点明是什么，再用一句话说明为什么重要。不要泛泛而谈。"
    ],
    "difficulties": "找出本章中读者可能卡住的地方：专业术语、文化背景、隐晦的表达、复杂的逻辑链等，用大白话解释清楚。如果没有难点就坦诚说明。",
    "insight": "分享一个有启发性的深层解读：可以是与其他作品的对比、一个反直觉的发现、当下社会的映射、或者作者没有明说但暗含的立场。要言之有物，避免空洞的感悟。"
}}"""

    try:
        text, used_model = await _ai_complete(prompt, temperature=0.3, max_tokens=8192, task='analyze')

        # Robust JSON cleaning
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}")+1]

        result = json.loads(text)
        result["_model"] = used_model
        _analysis_cache[cache_key] = result # Cache the processed object
        return result
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Analysis failed: invalid JSON from AI")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")

@app.post("/api/ai/translate")
async def translate_text(req: dict):
    """Translate text using unified AI dispatch."""
    text = req.get("text", "")
    if not text:
        return {"translation": ""}

    # Auto-detect: if mostly CJK → translate to English, otherwise → translate to Chinese
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
    target = "英文" if cjk_count > len(text) * 0.3 else "中文"

    prompt = f"""请将以下文本翻译成{target}。

翻译要求：
- 准确传达原意，语句通顺自然，符合{target}的表达习惯
- 专有名词（人名、地名、术语）首次出现时附注原文
- 保留原文的语气和风格（正式/口语/文学/技术）
- 只返回译文，不要解释

原文：
{text}"""

    try:
        result, _ = await _ai_complete(prompt, temperature=0.1, max_tokens=4096, task='translate')
        return {"translation": result.strip()}
    except Exception as e:
        return {"translation": f"[Translation Error: {str(e)}]"}


@app.post("/api/ai/translate-stream")
async def translate_text_stream(req: dict):
    """Translate text with streaming output using unified AI dispatch."""
    text = req.get("text", "")
    if not text:
        return StreamingResponse(iter([""]), media_type="text/plain")

    # Auto-detect: if mostly CJK → translate to English, otherwise → translate to Chinese
    cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
    target = "英文" if cjk_count > len(text) * 0.3 else "中文"

    # Build context from book metadata
    context = ""
    book_id = req.get("book_id")
    chapter_index = req.get("chapter_index")
    if book_id:
        book = load_book_cached(book_id)
        if book:
            meta = book.metadata
            parts = [f"书名《{meta.title}》"]
            if meta.authors:
                parts.append(f"作者{', '.join(meta.authors)}")
            if chapter_index is not None and 0 <= chapter_index < len(book.spine):
                ch_title = book.spine[chapter_index].title
                if ch_title:
                    parts.append(f"当前章节「{ch_title}」")
            context = f"[{', '.join(parts)}] "

    prompt = f"{context}将以下内容完整翻译成{target}，所有词汇都必须翻译，不得保留原文（专有名词首次出现时括号附注原文除外），只返回译文：\n{text}"

    gen = await _ai_stream(prompt, temperature=0.1, max_tokens=4096, task='translate')
    return StreamingResponse(_sanitized_stream(gen), media_type="text/plain; charset=utf-8")


@app.post("/api/quick-translate")
async def quick_translate(req: dict):
    """Dict lookup (instant) → Google Translate fallback (~100ms). Chinese words get AI definitions."""
    text = (req.get("text") or "").strip()
    if not text:
        return {"translation": ""}
    _ai_log("QUICK-TRANSLATE text=%r", text)

    # Step 1: Try local dictionary for single words/short phrases
    dict_result = _dict_lookup(text)
    if dict_result:
        return {
            "source": "dict",
            "word": dict_result['word'],
            "phonetic": dict_result['phonetic'],
            "translation": dict_result['translation'],
            "definition": dict_result['definition'],
        }

    # Step 2: Chinese text → local Chinese dictionary (457K entries, <1ms)
    is_cjk = _detect_cjk_ratio(text) > 0.3
    if is_cjk:
        cn_result = _cn_dict_lookup(text)
        if cn_result:
            return {
                "source": "cn-dict",
                "word": cn_result['word'],
                "pinyin": cn_result['pinyin'],
                "translation": cn_result['definition'],
            }

    # Step 3: Chinese text → AI definition (fallback for words not in local dict)
    if is_cjk and len(text) <= 20:
        defn = await _chinese_define(text)
        if defn:
            return {"source": "ai-dict", "word": text, "translation": defn}

    # Step 4: AI translation (preferred — user's configured provider, e.g. DeepSeek)
    dest = 'en' if is_cjk else 'zh-CN'
    target = "英文" if is_cjk else "中文"
    try:
        prompt = f"请将以下文本翻译成{target}，只返回译文，不要解释：\n{text}"
        result, _ = await _ai_complete(prompt, temperature=0.1, max_tokens=4096, task='translate')
        if result and result.strip():
            return {"source": "ai", "translation": result.strip()}
    except Exception:
        pass

    # Step 5: Fallback to Google Translate (may be unreachable in some regions)
    try:
        translation = await _google_translate(text, dest)
        return {"source": "google", "translation": translation}
    except Exception as e:
        return {"source": "error", "translation": "", "error": str(e)}


@app.post("/api/wiki-lookup")
async def wiki_lookup(req: dict):
    """Wikipedia summary for a term."""
    text = (req.get("text") or "").strip()
    if not text:
        return {"extract": ""}
    result = await _wiki_summary(text)
    return result


@app.post("/api/ai-explain")
async def ai_explain(req: dict):
    """用 AI 解释选中的术语/概念是什么（结合技术背景，中文回答）。"""
    text = (req.get("text") or "").strip()
    if not text:
        return {"explanation": ""}
    prompt = f"""请解释下面这个术语/概念是什么，帮助我理解技术文档。

要求：
- 用中文回答
- 先一句话给出定义，再补充作用/原理/在文档中的意义（若有）
- 简明扼要，3~6 句话即可，不要长篇大论
- 如果它是寄存器名、命令、信号、引脚等，说明它在硬件/通信中的作用
- 只返回解释内容，不要加"好的""以下是解释"等前缀

待解释内容：
{text[:2000]}"""
    try:
        result, _ = await _ai_complete(prompt, temperature=0.3, max_tokens=1000, task='chat')
        return {"explanation": (result or "").strip()}
    except Exception as e:
        return {"explanation": "", "error": str(e)}


@app.post("/api/search")
async def search_book(req: dict):
    """Full-text search across all chapters of a book."""
    book_id = (req.get("book_id") or "").strip()
    query = (req.get("query") or "").strip()
    if not book_id or not query:
        return {"results": []}
    book = load_book_cached(book_id)
    if not book:
        return {"results": []}
    lower_q = query.lower()
    results = []
    for ch in book.spine:
        text = ch.text or ""
        lower_text = text.lower()
        pos = 0
        while (pos := lower_text.find(lower_q, pos)) != -1:
            start = max(0, pos - 40)
            end = min(len(text), pos + len(query) + 40)
            snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
            results.append({
                "chapterIndex": ch.order,
                "chapterTitle": ch.title,
                "snippet": snippet,
                "matchStart": pos,
            })
            pos += len(query)
            if len(results) >= 200:
                break
        if len(results) >= 200:
            break
    return {"results": results}


class AIChatRequest(BaseModel):
    book_id: str
    chapter_index: int
    question: str


@app.post("/api/ai/chat")
async def chat_about_chapter(req: AIChatRequest):
    """Answer a free-form question about the current chapter."""
    book = load_book_cached(req.book_id)
    if not book or req.chapter_index < 0 or req.chapter_index >= len(book.spine):
        raise HTTPException(status_code=404, detail="Chapter not found")
    chapter = book.spine[req.chapter_index]

    # Use text field, fallback to stripping HTML from content
    chapter_text = chapter.text.strip()
    if not chapter_text and chapter.content:
        from html.parser import HTMLParser
        class _Strip(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []
            def handle_data(self, d):
                self.parts.append(d)
        s = _Strip()
        s.feed(chapter.content)
        chapter_text = ' '.join(s.parts).strip()

    prompt = f"""你是这本书的深度阅读伙伴。基于章节内容回答问题时：
- 尽量引用原文中的具体段落或细节来支撑回答
- 如果问题涉及更广的背景知识，可以拓展，但要标注哪些是原文内容、哪些是补充
- 用与提问者相同的语言回答
- 回答要有条理，必要时使用小标题分段

书名：{book.metadata.title}
作者：{', '.join(book.metadata.authors) if book.metadata.authors else '未知'}
章节：{chapter.title}

【章节内容】：
{chapter_text[:12000]}

【读者提问】：
{req.question}"""

    try:
        gen = await _ai_stream(prompt, temperature=0.7, max_tokens=4096, task='chat')
        return StreamingResponse(_sanitized_stream(gen), media_type="text/plain; charset=utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


@app.post("/api/ai/chat-context")
async def chat_with_context(req: dict):
    """AI chat with arbitrary text context (for PDF reader etc.)."""
    question = (req.get("question") or "").strip()
    context = (req.get("context") or "").strip()
    title = (req.get("title") or "").strip()
    history = req.get("history") or []
    images = req.get("images") or []
    provider_id = (req.get("provider_id") or "").strip() or None
    if not question and not images:
        raise HTTPException(status_code=400, detail="No question provided")
    if not question:
        question = "请看图片，并回答相关问题。"

    _ai_log("CHAT-CONTEXT question=%r context_len=%d title=%r history_len=%d images=%d", question, len(context), title, len(history), len(images))

    parts = []
    if title:
        parts.append(f"当前阅读：《{title}》")

    # 对话历史：让 AI 具备多轮上下文记忆
    hist_lines = []
    for h in history[-12:]:
        if not isinstance(h, dict):
            continue
        role = h.get("role")
        content = (h.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            hist_lines.append(f"用户：{content}")
        elif role in ("ai", "assistant"):
            hist_lines.append(f"助手：{content}")
    if hist_lines:
        parts.append("【对话历史】（请结合历史上下文回答，保持连贯；若用户要求切换语言，请按要求执行）：\n" + "\n".join(hist_lines))

    if images:
        parts.append("【用户提供了图片】，请结合图片内容回答。")

    if context:
        parts.append(f"【选中文本】：\n{context[:6000]}")
    parts.append(f"【当前提问】：{question}")

    prompt = "你是一位知识渊博的阅读助手。用与提问者相同的语言回答。回答要有条理。" \
             "请使用 Markdown 格式排版（用 **加粗**、- 列表、1. 编号、## 标题等），" \
             "不要使用 HTML 标签（如 <p>、<strong>、<div> 等）。" \
             "如果提供了选中文本，请结合该文本来回答。" \
             "如果提供了图片，请仔细观察图片内容并结合图片回答。" \
             "如果提供了对话历史，请结合历史上下文理解当前提问（例如用户说“用中文回答”是要你把之前的内容用中文重述）。\n\n" + "\n\n".join(parts)

    try:
        gen = await _ai_stream(prompt, temperature=0.7, max_tokens=4096, task='chat', images=images)
        return StreamingResponse(_sanitized_stream(gen), media_type="text/plain; charset=utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


# --- AI Provider Management API ---

@app.get("/api/ai/providers")
async def get_providers():
    """Return provider list with status (key masked)."""
    _load_ai_config()
    result = []
    seen = set()
    def _entry(pid, p):
        defn = _PROVIDER_DEFS.get(pid, {})
        if not defn and pid.startswith('custom'):
            defn = _PROVIDER_DEFS.get('custom', {})
        key = p.get('api_key', '')
        name = p.get('custom_name') or defn.get('name', pid)
        # ollama/cli 无需 API Key，用 enabled 判断"已配置"
        if pid in ('ollama', 'cli'):
            has_key = bool(p.get('enabled'))
        else:
            has_key = bool(key)
        entry = {
            'id': pid, 'name': name,
            'has_key': has_key, 'key_preview': key[:3] + '******' + key[-3:] if len(key) > 6 else ('******' if key else ''),
            'enabled': p.get('enabled', False),
            'model': p.get('model') or defn.get('default_model', ''),
            'base_url': p.get('base_url', ''),
            'default_model': defn.get('default_model', ''),
            'default_base_url': defn.get('base_url', ''),
            'vision_model': p.get('vision_model', ''),
            'default_vision_model': defn.get('vision_model', ''),
            'cli_command': p.get('cli_command', ''),
        }
        if p.get('temperature') is not None:
            entry['temperature'] = p['temperature']
        if p.get('max_tokens') is not None:
            entry['max_tokens'] = p['max_tokens']
        if pid.startswith('custom'):
            entry['custom_name'] = p.get('custom_name', '')
        return entry
    # Build map of builtin keys for filtering migrated entries
    builtin_keys = {pid: bkey for pid, bkey, _ in _get_builtin_providers()}
    for pid in _ai_config.get('order', []):
        if pid in _ai_config.get('providers', {}):
            p = _ai_config['providers'][pid]
            # Skip entries whose key matches a builtin .env key (legacy migration artifacts)
            if pid in builtin_keys and p.get('api_key') == builtin_keys[pid]:
                continue
            seen.add(pid)
            result.append(_entry(pid, p))
    for pid, p in _ai_config.get('providers', {}).items():
        if pid not in seen:
            if pid in builtin_keys and p.get('api_key') == builtin_keys[pid]:
                continue
            result.append(_entry(pid, p))
    return {"providers": result, "available": list(_PROVIDER_DEFS.keys()),
            "task_routing": _ai_config.get('task_routing', {}),
            "local_clis": _detect_local_clis()}


@app.post("/api/ai/providers")
async def save_providers(req: dict):
    """Save provider configuration. Empty api_key = keep existing key."""
    providers = req.get('providers', [])
    old_providers = _ai_config.get('providers', {})
    _ai_config['providers'] = {}
    _ai_config['order'] = []
    for p in providers:
        pid = p.get('id', '')
        if not pid:
            continue
        _ai_config['order'].append(pid)
        new_key = p.get('api_key', '')
        # If no new key provided, keep the old one
        if not new_key and pid in old_providers:
            new_key = old_providers[pid].get('api_key', '')
        _ai_config['providers'][pid] = {
            'api_key': new_key,
            'enabled': p.get('enabled', False),
            'model': p.get('model', ''),
            'base_url': p.get('base_url', ''),
            'vision_model': p.get('vision_model', ''),
            'cli_command': p.get('cli_command', ''),
        }
        if pid.startswith('custom') and p.get('custom_name'):
            _ai_config['providers'][pid]['custom_name'] = p['custom_name']
        if p.get('temperature') is not None:
            _ai_config['providers'][pid]['temperature'] = p['temperature']
        if p.get('max_tokens') is not None:
            _ai_config['providers'][pid]['max_tokens'] = p['max_tokens']
    # Save task routing if provided
    if 'task_routing' in req:
        _ai_config['task_routing'] = req['task_routing']
    _save_ai_config()
    _load_ai_config()
    return {"ok": True}


@app.post("/api/ai/test-provider")
async def test_provider(req: dict):
    """Test a provider's API key by making a minimal request."""
    pid = req.get('id', '')
    api_key = req.get('api_key', '')
    model_name = req.get('model', '')
    base_url = req.get('base_url', '')
    defn = _PROVIDER_DEFS.get(pid, {})
    if not defn and pid.startswith('custom'):
        defn = _PROVIDER_DEFS.get('custom', {})
    fmt = defn.get('format', 'openai')
    # Fallback to stored key if not provided
    if not api_key and pid in _ai_config.get('providers', {}):
        api_key = _ai_config['providers'][pid].get('api_key', '')
    if pid in ('ollama', 'cli'):
        api_key = 'local'  # 本地服务无需 key
    if not api_key:
        return {"ok": False, "message": "No API key provided"}
    if not model_name:
        model_name = defn.get('default_model', '')

    if fmt == 'cli':
        cli_cmd = req.get('cli_command', '') or _ai_config.get('providers', {}).get(pid, {}).get('cli_command', '')
        if not cli_cmd:
            return {"ok": False, "message": "未配置 CLI 命令模板"}
        try:
            out = await _call_cli(cli_cmd, "请回复：ok")
            return {"ok": True, "message": f"CLI 正常：{out[:80]}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    if fmt == 'gemini':
        try:
            client = google_genai.Client(api_key=api_key)
            resp = await asyncio.to_thread(lambda: client.models.generate_content(model=model_name, contents="Say 'ok'"))
            return {"ok": True, "message": f"Connected: {model_name}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    if not base_url:
        base_url = defn.get('base_url', '')
    if not base_url:
        return {"ok": False, "message": "No base URL configured"}
    def _extract_error(resp):
        """Extract human-readable error from API response."""
        try:
            body = resp.json()
            # OpenAI / DashScope / most providers: {"error": {"message": "..."}}
            err = body.get('error') or body.get('errors') or {}
            if isinstance(err, dict):
                msg = err.get('message', '')
                code = err.get('code', '')
                return f"{code}: {msg}" if code else msg
            if isinstance(err, str):
                return err
            return str(body)[:200]
        except Exception:
            return resp.text[:200] if hasattr(resp, 'text') else f"HTTP {resp.status_code}"

    try:
        if fmt == 'anthropic':
            async with httpx.AsyncClient(timeout=15, trust_env=True, headers={"User-Agent": "FixedPDF/1.0"}) as client:
                resp = await client.post(
                    f"{base_url.rstrip('/')}/messages",
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                    json={"model": model_name, "max_tokens": 10, "messages": [{"role": "user", "content": "Say ok"}]},
                )
                if resp.status_code != 200:
                    return {"ok": False, "message": _extract_error(resp)}
                return {"ok": True, "message": f"Connected: {model_name}"}
        else:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            body = {"model": model_name, "messages": [{"role": "user", "content": "Say ok"}], "max_tokens": 10}
            if pid == 'zhipuai':
                body["thinking"] = {"type": "disabled"}
            async with httpx.AsyncClient(timeout=15, trust_env=True, headers={"User-Agent": "FixedPDF/1.0"}) as client:
                resp = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json=body)
                if resp.status_code != 200:
                    return {"ok": False, "message": _extract_error(resp)}
                return {"ok": True, "message": f"Connected: {model_name}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/ai/export-config")
async def export_config():
    """Export AI provider config as downloadable JSON file."""
    _load_ai_config()
    from fastapi.responses import Response
    content = json.dumps(_ai_config, indent=2, ensure_ascii=False)
    return Response(content=content, media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=ai_config.json"})


@app.post("/api/ai/import-config")
async def import_config(req: dict):
    """Import AI provider config from uploaded JSON."""
    if 'providers' not in req or not isinstance(req['providers'], dict):
        raise HTTPException(status_code=400, detail="Invalid config: missing 'providers' object")
    global _ai_config
    _ai_config = req
    _ai_config.setdefault('order', list(req['providers'].keys()))
    _ai_config.setdefault('task_routing', {})
    _save_ai_config()
    _load_ai_config()
    return {"ok": True, "count": len(_ai_config['providers'])}


@app.post("/api/ai/fetch-models")
async def fetch_models(req: dict):
    """Fetch available models from a provider."""
    pid = req.get('id', '')
    api_key = req.get('api_key', '')
    base_url = req.get('base_url', '')
    defn = _PROVIDER_DEFS.get(pid, {})
    if not defn and pid.startswith('custom'):
        defn = _PROVIDER_DEFS.get('custom', {})
    fmt = defn.get('format', 'openai')
    # 本地 CLI 不通过 HTTP 暴露模型列表，其可用模型由 CLI 自身管理
    if fmt == 'cli':
        return {"models": [], "error": "本地 CLI 的模型由该命令行工具自行管理，无法列出。"}
    # Fallback to stored key if not provided
    if not api_key and pid in _ai_config.get('providers', {}):
        api_key = _ai_config['providers'][pid].get('api_key', '')
    if pid in ('ollama', 'cli'):
        api_key = 'local'  # 本地服务无需 key
    if not api_key:
        return {"models": [], "error": "No API key provided"}

    try:
        if fmt == 'gemini':
            client = google_genai.Client(api_key=api_key)
            models = await asyncio.to_thread(lambda: [m.name.replace('models/', '') for m in client.models.list() if 'generateContent' in (m.supported_actions or [])])
            return {"models": models}
    except Exception as e:
        return {"models": [], "error": str(e)}

    if not base_url:
        base_url = defn.get('base_url', '')
    if not base_url:
        return {"models": [], "error": "No base URL configured"}

    try:
        if fmt == 'anthropic':
            async with httpx.AsyncClient(timeout=15, trust_env=True, headers={"User-Agent": "FixedPDF/1.0"}) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/models", headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})
                resp.raise_for_status()
                data = resp.json()
                models = [m['id'] for m in data.get('data', [])]
                return {"models": models}
        else:
            async with httpx.AsyncClient(timeout=15, trust_env=True, headers={"User-Agent": "FixedPDF/1.0"}) as client:
                resp = await client.get(f"{base_url.rstrip('/')}/models", headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                data = resp.json()
                # Handle both {"data": [...]} (OpenAI) and [...] (Together AI) formats
                items = data.get('data', data) if isinstance(data, dict) else data
                models = [m['id'] for m in items if isinstance(m, dict) and 'id' in m]
                return {"models": sorted(models)}
    except Exception as e:
        return {"models": [], "error": str(e)}


# --- Dictionary Management API ---

@app.get("/api/dict/status")
async def dict_status():
    """Return dictionary install status and download URL availability."""
    dict_url = _ai_config.get('dict_url', '').strip() or _DEFAULT_DICT_URL
    items = {}
    for did, info in _DICT_FILES.items():
        path = os.path.join(_DICT_DIR, info['filename'])
        exists = os.path.exists(path)
        items[did] = {
            'label': info['label'], 'label_en': info['label_en'],
            'installed': exists,
            'size_mb': round(os.path.getsize(path) / 1048576) if exists else info['size_mb'],
            'gz_mb': info['gz_mb'],
        }
    return {'dicts': items, 'has_url': bool(dict_url)}


_dict_downloading = set()  # prevent concurrent downloads

@app.post("/api/dict/download")
async def download_dict(req: dict):
    """Download and decompress a dictionary file. Streams SSE progress."""
    dict_id = req.get('id', '')
    info = _DICT_FILES.get(dict_id)
    if not info:
        raise HTTPException(status_code=400, detail="Unknown dictionary id")
    if dict_id in _dict_downloading:
        raise HTTPException(status_code=409, detail="Already downloading")
    dict_url = _ai_config.get('dict_url', '').strip() or _DEFAULT_DICT_URL
    gz_url = f"{dict_url.rstrip('/')}/{info['filename']}.gz"
    dest = os.path.join(_DICT_DIR, info['filename'])
    tmp = dest + '.tmp'
    expected_gz = info['gz_mb'] * 1048576  # fallback total size

    async def stream():
        _dict_downloading.add(dict_id)
        try:
            import urllib.request
            os.makedirs(_DICT_DIR, exist_ok=True)
            decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)

            def _download():
                req = urllib.request.Request(gz_url, headers={'User-Agent': 'FixedPDF/1.0'})
                proxy_url = _ai_config.get('proxy', '').strip()
                if proxy_url:
                    handler = urllib.request.ProxyHandler({
                        'http': proxy_url, 'https': proxy_url,
                    })
                    opener = urllib.request.build_opener(handler)
                else:
                    opener = urllib.request.build_opener()  # respects env http_proxy
                return opener.open(req, timeout=300)

            resp = await asyncio.to_thread(_download)
            total = int(resp.headers.get('Content-Length', 0)) or expected_gz
            downloaded = 0
            last_pct = -1
            with open(tmp, 'wb') as f:
                while True:
                    chunk = await asyncio.to_thread(resp.read, 65536)
                    if not chunk:
                        break
                    decompressed = decomp.decompress(chunk)
                    f.write(decompressed)
                    downloaded += len(chunk)
                    pct = min(int(downloaded * 100 / total), 99) if total else 0
                    if pct > last_pct:
                        last_pct = pct
                        yield f"data: {json.dumps({'progress': pct})}\n\n"
                remaining = decomp.flush()
                if remaining:
                    f.write(remaining)
            if os.path.exists(tmp):
                os.replace(tmp, dest)
                _reload_dict()
                yield f"data: {json.dumps({'done': True})}\n\n"
            else:
                yield f"data: {json.dumps({'error': 'Download failed: temp file missing'})}\n\n"
        except Exception as e:
            if os.path.exists(tmp):
                os.unlink(tmp)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            _dict_downloading.discard(dict_id)

    return StreamingResponse(stream(), media_type='text/event-stream')


# --- TTS MODULE: edge-tts (local, free, low latency) ---

@app.get("/api/tts")
async def stream_tts(text: str, voice: str = "zh-CN-XiaoxiaoNeural", rate: str = "+0%"):
    """Stream TTS audio via edge-tts."""
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    async def generate():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    return StreamingResponse(generate(), media_type="audio/mpeg")

# --- Apple Books Integration ---

APPLE_BOOKS_DB = os.path.expanduser(
    "~/Library/Containers/com.apple.iBooksX/Data/Documents/BKLibrary/BKLibrary-1-091020131601.sqlite"
)
APPLE_BOOKS_COVER_DIR = os.path.expanduser(
    "~/Library/Containers/com.apple.iBooksX/Data/Library/Caches/BCCoverCache-1/BICDiskDataStore"
)

@app.get("/api/apple-books")
async def list_apple_books():
    """List books from Apple Books library."""
    if not os.path.exists(APPLE_BOOKS_DB):
        return {"books": [], "error": "Apple Books database not found"}

    def _query():
        conn = sqlite3.connect(APPLE_BOOKS_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ZTITLE, ZAUTHOR, ZPATH, ZFILESIZE, ZASSETID FROM ZBKLIBRARYASSET "
            "WHERE ZTITLE IS NOT NULL AND ZPATH IS NOT NULL AND ZCONTENTTYPE = 1 "
            "ORDER BY ZTITLE"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    rows = await asyncio.to_thread(_query)

    # Build a set of imported book titles (extracted from directory names) for fuzzy matching
    imported_titles = set()
    if os.path.isdir(BOOKS_DIR):
        for d in os.listdir(BOOKS_DIR):
            if d.endswith("_data") and os.path.exists(os.path.join(BOOKS_DIR, d, "book.pkl")):
                # "失衡的免疫 - 【法】蒙蒂·莱曼_data" → "失衡的免疫"
                name = d[:-5]  # strip "_data"
                title_part = name.split(" - ")[0].strip()
                imported_titles.add(title_part.lower())

    def _normalize(s):
        """Strip punctuation and whitespace for fuzzy title comparison."""
        return _re.sub(r'[\s\W]+', '', s).lower()

    imported_normalized = {_normalize(t): t for t in imported_titles}

    def _is_imported(r):
        # 1. Check by epub filename
        base_name = os.path.splitext(os.path.basename(r['ZPATH']))[0]
        if os.path.exists(os.path.join(BOOKS_DIR, base_name + "_data", "book.pkl")):
            return True
        # 2. Check by Apple Books title + author
        title_name = _safe_dirname(r['ZTITLE'], [r['ZAUTHOR']] if r['ZAUTHOR'] else None)
        if os.path.exists(os.path.join(BOOKS_DIR, title_name + "_data", "book.pkl")):
            return True
        # 3. Fuzzy: require full normalized equality (prefix match too loose for serials)
        ab_norm = _normalize(r['ZTITLE'])
        if ab_norm in imported_normalized:
            return True
        return False

    books = []
    for r in rows:
        path = r['ZPATH']
        if not path or not os.path.exists(path):
            continue
        books.append({
            "title": r['ZTITLE'],
            "author": r['ZAUTHOR'] or '',
            "path": path,
            "size_mb": round((r['ZFILESIZE'] or 0) / 1048576, 1),
            "imported": _is_imported(r),
            "asset_id": r['ZASSETID'] or '',
        })
    return {"books": books}


@app.get("/api/apple-books/cover/{asset_id}")
async def serve_apple_books_cover(asset_id: str):
    """Serve a cover image from Apple Books cache."""
    import subprocess
    safe_id = os.path.basename(asset_id)
    cover_dir = os.path.join(APPLE_BOOKS_COVER_DIR, safe_id)
    if not os.path.isdir(cover_dir):
        raise HTTPException(status_code=404, detail="Cover not found")
    # Check for cached JPEG first
    jpeg_path = os.path.join(cover_dir, f"{safe_id}.jpg")
    if os.path.exists(jpeg_path) and os.path.getsize(jpeg_path) > 0:
        return FileResponse(jpeg_path, media_type="image/jpeg")
    # Find largest HEIC file (best quality)
    import glob as _glob
    heics = sorted(_glob.glob(os.path.join(cover_dir, "*.heic")), key=os.path.getsize, reverse=True)
    if not heics:
        raise HTTPException(status_code=404, detail="No cover image")
    # Convert HEIC to JPEG synchronously (awaited)
    await asyncio.to_thread(
        subprocess.run,
        ["sips", "-s", "format", "jpeg", heics[0], "--out", jpeg_path],
        capture_output=True, timeout=10
    )
    if os.path.exists(jpeg_path) and os.path.getsize(jpeg_path) > 0:
        return FileResponse(jpeg_path, media_type="image/jpeg")
    raise HTTPException(status_code=500, detail="Cover conversion failed")


@app.post("/api/import-local")
async def import_local_epub(req: dict):
    """Import an EPUB or PDF from a local file path (e.g. Apple Books)."""
    path = req.get("path", "")
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=400, detail="File not found")
    path_lower = path.lower()
    if not (path_lower.endswith('.epub') or path_lower.endswith('.pdf')):
        raise HTTPException(status_code=400, detail="Only .epub and .pdf files are supported")

    is_pdf = path_lower.endswith('.pdf')
    base_name = os.path.splitext(os.path.basename(path))[0]
    out_dir = os.path.join(BOOKS_DIR, base_name + "_data")

    if is_pdf:
        meta_info = await asyncio.to_thread(_process_pdf, path, out_dir)
        title_name = _safe_dirname(meta_info['title'], [meta_info['author']] if meta_info['author'] else None)
        title_dir = os.path.join(BOOKS_DIR, title_name + "_data")
        if title_name and title_dir != out_dir and not os.path.exists(title_dir):
            os.rename(out_dir, title_dir)
            out_dir = title_dir
        book_id = os.path.basename(out_dir)
        return {
            "success": True,
            "book_id": book_id,
            "title": meta_info['title'],
            "chapters": meta_info['pages'],
            "has_cover": True,
        }

    book_obj = await asyncio.to_thread(process_epub, path, out_dir)
    await asyncio.to_thread(save_to_pickle, book_obj, out_dir)

    # Rename directory to book title if different from filename
    import shutil
    title_name = _safe_dirname(book_obj.metadata.title, book_obj.metadata.authors)
    title_dir = os.path.join(BOOKS_DIR, title_name + "_data")
    if title_name and title_dir != out_dir and not os.path.exists(title_dir):
        os.rename(out_dir, title_dir)
        out_dir = title_dir
    book_id = os.path.basename(out_dir)

    # Keep a copy of the epub for future reprocessing
    epub_copy = os.path.join(out_dir, "source.epub")
    if not os.path.exists(epub_copy):
        try:
            shutil.copy2(path, epub_copy)
        except (OSError, PermissionError):
            # Apple Books sandbox may block metadata copy; fallback to content-only copy
            try:
                shutil.copy(path, epub_copy)
            except Exception:
                pass  # Non-critical: source.epub is only for reprocessing

    load_book_cached.cache_clear()

    return {
        "success": True,
        "book_id": book_id,
        "title": book_obj.metadata.title,
        "chapters": len(book_obj.spine),
        "has_cover": _find_cover_image(book_id) is not None,
    }


@app.post("/api/upload")
async def upload_epub(file: UploadFile = File(...)):
    """Upload and process an EPUB or PDF file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    fname_lower = file.filename.lower()
    if not (fname_lower.endswith('.epub') or fname_lower.endswith('.pdf')):
        raise HTTPException(status_code=400, detail="Only .epub and .pdf files are supported")

    is_pdf = fname_lower.endswith('.pdf')
    suffix = '.pdf' if is_pdf else '.epub'

    # Save to temp file
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Determine output dir name
        base_name = os.path.splitext(file.filename)[0]
        out_dir = os.path.join(BOOKS_DIR, base_name + "_data")

        if is_pdf:
            meta_info = await asyncio.to_thread(_process_pdf, tmp_path, out_dir)
            # Rename directory to title if different from filename
            title_name = _safe_dirname(meta_info['title'], [meta_info['author']] if meta_info['author'] else None)
            title_dir = os.path.join(BOOKS_DIR, title_name + "_data")
            if title_name and title_dir != out_dir and not os.path.exists(title_dir):
                os.rename(out_dir, title_dir)
                out_dir = title_dir
            book_id = os.path.basename(out_dir)
            return {
                "success": True,
                "book_id": book_id,
                "title": meta_info['title'],
                "chapters": meta_info['pages'],
                "has_cover": True,
            }
        else:
            # Process in thread to avoid blocking
            book_obj = await asyncio.to_thread(process_epub, tmp_path, out_dir)
            await asyncio.to_thread(save_to_pickle, book_obj, out_dir)

            # Rename directory to book title if different from filename
            title_name = _safe_dirname(book_obj.metadata.title, book_obj.metadata.authors)
            title_dir = os.path.join(BOOKS_DIR, title_name + "_data")
            if title_name and title_dir != out_dir and not os.path.exists(title_dir):
                os.rename(out_dir, title_dir)
                out_dir = title_dir
            book_id = os.path.basename(out_dir)

            # Keep a copy of the epub for future reprocessing
            import shutil
            shutil.copy2(tmp_path, os.path.join(out_dir, "source.epub"))

            # Clear LRU cache so new book appears
            load_book_cached.cache_clear()

            return {
                "success": True,
                "book_id": book_id,
                "title": book_obj.metadata.title,
                "chapters": len(book_obj.spine),
                "has_cover": _find_cover_image(book_id) is not None,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process file: {str(e)}")
    finally:
        os.unlink(tmp_path)


@app.post("/api/reprocess/{book_id}")
async def reprocess_book(book_id: str):
    """Reprocess a book from its saved source.epub."""
    safe_id = os.path.basename(book_id)
    book_dir = os.path.join(BOOKS_DIR, safe_id)
    source_epub = os.path.join(book_dir, "source.epub")
    if not os.path.exists(source_epub):
        raise HTTPException(status_code=400, detail="No source epub found. Please re-upload the book.")

    # Copy source.epub to a temp file OUTSIDE book_dir,
    # because process_epub will rmtree the entire book_dir
    import shutil
    tmp_fd, tmp_epub = tempfile.mkstemp(suffix='.epub')
    os.close(tmp_fd)
    shutil.copy2(source_epub, tmp_epub)

    try:
        book_obj = await asyncio.to_thread(process_epub, tmp_epub, book_dir)
        await asyncio.to_thread(save_to_pickle, book_obj, book_dir)
        # Restore source.epub into the fresh output dir
        shutil.copy2(tmp_epub, os.path.join(book_dir, "source.epub"))
        load_book_cached.cache_clear()
        # Clear AI analysis cache for this book so stale results aren't served
        stale_keys = [k for k in _analysis_cache if k.startswith(f"{safe_id}:")]
        for k in stale_keys:
            del _analysis_cache[k]
        return {"success": True, "title": book_obj.metadata.title}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reprocess failed: {str(e)}")
    finally:
        if os.path.exists(tmp_epub):
            os.unlink(tmp_epub)


# --- PDF Reader Routes ---

@app.get("/read-pdf/{book_id}", response_class=HTMLResponse)
async def read_pdf(request: Request, book_id: str):
    """Render PDF reader page."""
    safe_id = os.path.basename(book_id)
    meta_path = os.path.join(BOOKS_DIR, safe_id, "meta.json")
    if not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="PDF book not found")
    with open(meta_path, encoding='utf-8') as f:
        meta = json.load(f)
    # Check for display_title in library index
    index = _build_library_index()
    display_title = index.get(safe_id, {}).get('display_title')
    resp = templates.TemplateResponse("pdf_reader.html", {
        "request": request,
        "book_id": safe_id,
        "title": display_title or meta.get('title', 'Untitled'),
        "pages": meta.get('pages', 0),
        "outline_json": json.dumps(meta.get('outline', []), ensure_ascii=False),
    })
    # 强制不缓存，确保浏览器始终加载最新前端脚本
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.get("/api/pdf-file/{book_id}")
async def serve_pdf_file(book_id: str):
    """Serve the PDF file for the reader."""
    safe_id = os.path.basename(book_id)
    pdf_path = os.path.join(BOOKS_DIR, safe_id, "book.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(pdf_path, media_type="application/pdf")


# Structured translations are actual PDFs, shared by preview and download.
_pdf_generation_locks = {}


def _structured_pdf_source(book_id: str) -> Path:
    root = Path(BOOKS_DIR).resolve()
    folder = (root / book_id).resolve()
    if folder.parent != root or not book_id or '/' in book_id or '\\' in book_id:
        raise HTTPException(400, 'Invalid book id')
    source = folder / 'book.pdf'
    if not source.is_file() or source.resolve().parent != folder:
        raise HTTPException(404, 'PDF file not found')
    return source


def _structured_pdf_version(source: Path) -> str:
    # Keys never participate in reports, filenames or logs.
    providers = [{k: p.get(k) for k in ('id', 'base_url', 'model')} for p in _get_enabled_providers()]
    signature = json.dumps([providers, _ai_config.get('task_routing', {})], sort_keys=True)
    return pdf_translation.fingerprint(str(source), signature)


@app.post('/api/pdf-translation/{book_id}')
async def generate_pdf_translation(book_id: str, request: Request):
    source = _structured_pdf_source(book_id)
    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(400, 'Invalid JSON body') from exc
    if (not isinstance(body, dict) or type(body.get('force', False)) is not bool
            or type(body.get('cache_only', False)) is not bool):
        raise HTTPException(400, 'Expected an object and boolean force/cache_only')
    if body.get('force') and body.get('cache_only'):
        raise HTTPException(400, 'force and cache_only cannot both be true')
    page_number = body.get('page')
    if type(page_number) is not int or page_number < 1:
        raise HTTPException(400, 'page must be a positive integer')
    version = await asyncio.to_thread(_structured_pdf_version, source)
    folder = source.parent / '.translated' / version
    artifact = folder / f'page-{page_number}.pdf'
    metadata = folder / f'page-{page_number}.json'
    audit = folder / f'page-{page_number}.audit.json'
    key = str(artifact)
    lock = _pdf_generation_locks.setdefault(key, asyncio.Lock())
    async with lock:
        if artifact.is_file() and metadata.is_file() and not body.get('force', False):
            return json.loads(metadata.read_text(encoding='utf-8'))
        if body.get('cache_only'):
            raise HTTPException(404, '本页尚无已生成的译文。')
        try:
            plan = pdf_translation.analyze_page(str(source), page_number)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        targets = {}
        if audit.is_file():
            previous = json.loads(audit.read_text(encoding='utf-8'))
            sources = {r['id']: r['source'] for r in previous['plan']['regions']}
            targets = {r['id']: previous['targets'][r['id']] for r in plan['regions']
                       if sources.get(r['id']) == r['source'] and previous['targets'].get(r['id'])}
        pending = [r for r in plan['regions'] if r['id'] not in targets]
        new_targets, warnings = await pdf_translation.translate_regions({**plan, 'regions': pending}, _ai_complete)
        targets.update(new_targets)
        plan['warnings'].extend(warnings)
        try:
            report, targets = await pdf_translation.render_with_fit_retry(
                str(source), plan, targets, str(artifact), _ai_complete)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        report.update(version=version,
                      status='review' if report['warnings'] or report['pending_count'] or report['unplaced_count']
                      else 'ready',
                      pdf_url=f'/api/pdf-translation-file/{quote(book_id, safe="")}/{version}/{page_number}')
        # Store auditable IDs and translations locally, never provider credentials.
        audit.write_text(json.dumps({'plan': plan, 'targets': targets}, ensure_ascii=False), encoding='utf-8')
        temporary = metadata.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False), encoding='utf-8')
        temporary.replace(metadata)
        return report


@app.get('/api/pdf-translation-file/{book_id}/{version}/{page_number}')
async def translated_pdf_file(book_id: str, version: str, page_number: int):
    source = _structured_pdf_source(book_id)
    if not re.fullmatch(r'[a-f0-9]{24}', version) or page_number < 1:
        raise HTTPException(400, 'Invalid artifact')
    artifact = source.parent / '.translated' / version / f'page-{page_number}.pdf'
    if not artifact.is_file():
        raise HTTPException(404, 'Translation not generated')
    return FileResponse(artifact, media_type='application/pdf', filename=f'page-{page_number}-zh-CN.pdf')


@app.get('/api/pdf-translation-download/{book_id}/{version}')
async def download_translated_document(book_id: str, version: str):
    source = _structured_pdf_source(book_id)
    if not re.fullmatch(r'[a-f0-9]{24}', version):
        raise HTTPException(400, 'Invalid artifact')
    folder = source.parent / '.translated' / version
    def assemble():
        with pdf_translation.PDF_LOCK, pdf_translation.fitz.open(source) as original:
            paths = [folder / f'page-{i + 1}.pdf' for i in range(len(original))]
            if not all(p.is_file() for p in paths):
                raise HTTPException(409, 'Generate all pages before downloading')
            with pdf_translation.fitz.open() as result:
                for path in paths:
                    with pdf_translation.fitz.open(path) as translated:
                        result.insert_pdf(translated)
                return result.tobytes(garbage=4, deflate=True)
    data = assemble()
    return Response(data, media_type='application/pdf', headers={
        'Content-Disposition': "attachment; filename=translated-zh-CN.pdf"})


# --- 每本书的持久化存储：翻译缓存 + 对话记录 ---

_translation_lock = threading.Lock()


def _translation_cache_path(book_dir: str) -> str:
    return os.path.join(book_dir, "translation_cache.json")


def _load_translation_cache(book_dir: str) -> dict:
    path = _translation_cache_path(book_dir)
    try:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_translation_cache(book_dir: str, cache: dict):
    path = _translation_cache_path(book_dir)
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def _chat_history_path(book_dir: str) -> str:
    return os.path.join(book_dir, "chat_history.json")


# --- 段落级翻译缓存 ---

def _segment_cache_path(book_dir: str) -> str:
    return os.path.join(book_dir, "segment_cache.json")


def _load_segment_cache(book_dir: str) -> dict:
    path = _segment_cache_path(book_dir)
    try:
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_segment_cache(book_dir: str, cache: dict):
    path = _segment_cache_path(book_dir)
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


def _classify_pdf_block(text: str, x0: float, y0: float, x1: float, y1: float) -> str:
    """Classify a PDF text block so translation follows its fixed layout."""
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    line_count = len(lines)
    numeric_tokens = len(re.findall(r"(?:\d|\b(?:VCC|GND|VIN|VOUT|IOUT|ICC|ns|pF|mA)\b)", text, re.I))
    header_terms = len(re.findall(
        r"\b(?:symbol|parameter|conditions?|typ|guaranteed|limits?|units?)\b", text, re.I
    ))

    if height > width * 3:
        return "vertical"
    # Table headers can contain no numeric values at all.  A sequence of
    # standard column labels is a stronger table signal than its geometry.
    if line_count >= 3 and header_terms >= 3:
        return "table"
    # Short electrical-characteristic rows may contain just one value and
    # unit (for example, a propagation-delay row).  Their line breaks are
    # table cells emitted by the PDF, not prose.  Split them into spans so a
    # translated parameter can never occupy the whole row.
    technical_parameter = bool(re.search(
        r"\b(?:propagation|rise|fall|delay|capacitance|frequency|current|"
        r"voltage|temperature|power)\b", text, re.I
    ))
    if line_count >= 4 and numeric_tokens >= 1 and technical_parameter and width > height * 6:
        return "table"
    # A wide paragraph is not a table.  It must also carry several numerical
    # values (the usual signature of a data-sheet row) before we split it.
    if line_count >= 4 and numeric_tokens >= 4:
        return "table"
    if line_count <= 2 and len(text) <= 48:
        return "label"
    return "paragraph"


def _normalise_segment_translation(text: str, layout: str) -> str:
    """Remove AI wrappers and make output safe for its original PDF rectangle."""
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    cleaned = re.sub(r"^(?:translation|translated text|译文|翻译|中文译文)\s*[:：]\s*", "", cleaned, flags=re.I)
    if layout in {"table", "table_cell", "label"}:
        return re.sub(r"\s*\n\s*", " ", cleaned)
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _should_translate_table_span(text: str) -> bool:
    """Select table labels while leaving values and signal names in place."""
    value = (text or "").strip()
    if len(value) < 2:
        return False
    compact = re.sub(r"\s+", "", value)
    if re.match(r"^[+-]?(?:\d|\.\d)", value):
        return False
    if re.fullmatch(r"[\d\s.,:+\-–—/%°()=<>]+", value):
        return False
    if re.fullmatch(r"[A-Z][A-Z0-9_/#.]*", value):
        return False
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[a-zA-Z°]+)?", compact):
        return False
    if re.fullmatch(r"(?:[kMmunp]?V|[kMmunp]?A|ns|us|ms|MHz|kHz|pF|nF|uF|°C)", value, re.I):
        return False
    words = re.findall(r"[A-Za-z]+", value)
    if words and all(word.isupper() or len(word) == 1 for word in words):
        return False
    if words and all(re.fullmatch(r"[a-z]?[A-Z]{2,}", word) for word in words):
        return False
    if re.search(r"\b(?:VIN|VOUT|IOUT|VCC|GND|ICC)\b", value, re.I) and not re.search(
        r"\b(?:minimum|maximum|input|output|supply|current|voltage|temperature)\b", value, re.I
    ):
        return False
    return bool(re.search(r"[A-Za-z]", value))


def _looks_like_table_signal(text: str) -> bool:
    """Return True for a compact sequence of circuit signal identifiers."""
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9]*", text or "")
    if not tokens:
        return False
    return all(re.fullmatch(r"(?:[a-z]|[A-Z]{2,5}|[a-z][A-Z]{2,5})", token) for token in tokens)


PDF_SEGMENT_CACHE_VERSION = "v8"


_TABLE_CELL_GLOSSARY = {
    "Absolute Maximum Ratings": "绝对最大额定值",
    "Absolute Maximum Ratings (Notes 1 & 2)": "绝对最大额定值（注1和注2）",
    "(Notes 1 & 2)": "（注1和注2）",
    "If Military /Aerospace specified devices are required,": "如需军用/航空航天指定器件，",
    "please contact the National Semiconductor Sales": "请联系国家半导体销售",
    "Office/Distributors for availability and specifications.": "办事处/分销商获取供货和规格。",
    "Operating Conditions": "工作条件",
    "DC Electrical Characteristics (Note 4)": "直流电气特性（注4）",
    "AC Electrical Characteristics": "交流电气特性",
    "Symbol": "符号",
    "Parameter": "参数",
    "Conditions": "条件",
    "Units": "单位",
    "Typ": "典型值",
    "Guaranteed Limit": "保证限值",
    "Guaranteed Limits": "保证限值",
    "Supply Voltage": "电源电压",
    "DC Input Voltage": "直流输入电压",
    "DC Output Voltage": "直流输出电压",
    "Clamp Diode Current": "钳位二极管电流",
    "DC Output Current, per pin": "每引脚直流输出电流",
    "or GND Current, per pin": "或 GND 每引脚电流",
    "Storage Temperature Range": "存储温度范围",
    "Power Dissipation": "功耗",
    "Min": "最小值",
    "Max": "最大值",
    "DC Input or Output Voltage": "直流输入或输出电压",
    "Operating Temp. Range": "工作温度范围",
    "Input Rise or Fall Times": "输入上升或下降时间",
    "Minimum High Level": "最小高电平",
    "Maximum Low Level": "最大低电平",
    "Maximum Low Level V": "最大低电平 V",
    "Input Voltage": "输入电压",
    "Input Voltage **": "输入电压**",
    "Output Voltage": "输出电压",
    "Maximum Input": "最大输入",
    "Maximum Quiescent": "最大静态",
    "Supply Current": "电源电流",
    "Current": "电流",
    "Minimum Propagation": "最小传播",
    "Minimum Propagation Delay": "最小传播延迟",
    "Maximum Propagation": "最大传播",
    "Maximum Propagation Delay": "最大传播延迟",
    "Delay": "延迟",
    "Maximum Output Rise": "最大输出上升",
    "Maximum Output Rise and Fall Time": "最大输出上升和下降时间",
    "and Fall Time": "和下降时间",
    "Power Dissipation": "功耗",
    "Capacitance": "电容",
}


def _calibrated_table_cell_translation(text: str) -> str | None:
    """Return a reviewed, compact Chinese label for common data-sheet cells."""
    source = re.sub(r"\s+", " ", text or "").strip()
    source = re.sub(r"\s*([,.;:])\s*", r"\1 ", source).strip()
    direct = _TABLE_CELL_GLOSSARY.get(source)
    if direct:
        return direct
    # PyMuPDF can split a parenthesized signal name across spans.  The visible
    # label is still stable enough to use the reviewed base translation.
    base_label = re.sub(r"\s*\([^)]*\)?$", "", source).strip()
    base_translation = _TABLE_CELL_GLOSSARY.get(base_label)
    if base_translation:
        signal = re.search(r"\(\s*([A-Za-z][A-Za-z0-9\s,/_]*)\s*\)", source)
        if signal:
            compact_signal = re.sub(r"\s+", "", signal.group(1))
            return f"{base_translation}（{compact_signal}）"
        return base_translation
    compact_source = re.sub(r"\s+", "", source)
    if compact_source.startswith("DCVCCorGNDCurrent"):
        return "VCC或GND每引脚电流（ICC）"
    return None


def _merge_pdf_heading_parts(blocks: list[dict], page_num: int) -> list[dict]:
    """Merge adjacent fragments that form one fixed-layout data-sheet label."""
    merged = []
    consumed = set()
    for index, first in enumerate(blocks):
        if index in consumed:
            continue
        # The PDF text stream is normally spatially ordered, but a stacked
        # column heading can be interrupted by a neighbouring column on the
        # same baseline (``Guaranteed``, ``Units``, ``Limit``).  Search the
        # nearby header fragments rather than assuming they are consecutive.
        for candidate_index in range(index + 1, min(len(blocks), index + 7)):
            if candidate_index in consumed:
                continue
            second = blocks[candidate_index]
            can_merge_heading = (
                first.get('layout') == 'table_cell'
                and second.get('layout') == 'table_cell'
                and re.search(r"\b(?:Ratings|Characteristics)$", first['source'], re.I)
                and second['source'].lstrip().startswith('(')
                and abs(first['y0'] - second['y0']) <= 4
                and abs(first['x1'] - second['x0']) <= 4
            )
            # PDF generators commonly put the last word of a narrow parameter
            # cell on a separate baseline.  It is still one visual cell:
            # combine only aligned, immediately adjacent fragments that have
            # a compact reviewed translation.
            can_merge_wrapped_label = (
                first.get('layout') == 'table_cell'
                and second.get('layout') == 'table_cell'
                and (
                    abs(first['x0'] - second['x0']) <= 2
                    or abs((first['x0'] + first['x1']) - (second['x0'] + second['x1'])) <= 4
                )
                and 0 <= second['y0'] - first['y1'] <= 4
                and second['x1'] <= first['x1'] + 2
                and len(first['source']) <= 48
                and len(second['source']) <= 24
            )
            if not (can_merge_heading or can_merge_wrapped_label):
                continue
            source = f"{first['source']} {second['source']}"
            if not _calibrated_table_cell_translation(source):
                continue
            combined = dict(first)
            combined.update({
                'x1': max(first['x1'], second['x1']),
                'y0': min(first['y0'], second['y0']),
                'y1': max(first['y1'], second['y1']),
                'width': round(max(first['x1'], second['x1']) - first['x0'], 2),
                'height': round(max(first['y1'], second['y1']) - min(first['y0'], second['y0']), 2),
                'source': source,
                'cache_key': f"table-{PDF_SEGMENT_CACHE_VERSION}:{page_num}:{hashlib.sha1(source.encode('utf-8')).hexdigest()[:12]}",
            })
            merged.append(combined)
            consumed.add(candidate_index)
            break
        else:
            merged.append(first)
    return merged


def _segment_translation_prompt(block: dict) -> str:
    """Build a layout-aware prompt for one fixed-coordinate PDF text block."""
    layout = block["layout"]
    instructions = {
        "paragraph": "This is a prose paragraph. Keep its meaning concise; preserve at most the meaningful paragraph breaks.",
        "label": "This is a heading or short label. Return one compact line only; do not add a line break.",
        "table_cell": "This is one textual cell inside a technical table. Translate only this label into one short line. Do not add values, units, columns, or line breaks.",
        "vertical": "This is vertical page artwork. Return a concise title only; do not add line breaks.",
    }[layout]
    return f"""Translate the following technical English PDF text block into accurate Simplified Chinese.
The result will be placed back into its original fixed rectangle, so layout is mandatory:
- Block type: {layout}; rectangle: {block['width']:.0f} x {block['height']:.0f} PDF points.
- {instructions}
- Preserve numbers, units, signal names, part numbers, formulas, and abbreviations exactly where possible.
- Do not add explanations, Markdown, prefixes, or suffixes.

Source text:
{block['source'][:4000]}"""


def _extract_pdf_blocks(pdf_path: str, page_num: int):
    """提取某页的文本块（段落）及其 PDF 坐标。"""
    import fitz
    doc = fitz.open(pdf_path)
    try:
        if page_num < 1 or page_num > len(doc):
            return None
        page = doc[page_num - 1]
        blocks = page.get_text("blocks")  # (x0,y0,x1,y1,text,block_no,block_type)
        dict_blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
        raw_blocks = []
        for b in blocks:
            x0, y0, x1, y1, text = b[0], b[1], b[2], b[3], b[4]
            text = (text or '').strip()
            if len(text) < 2:
                continue  # 过滤页码、页眉、图片块等
            raw_blocks.append({
                'x0': round(float(x0), 2), 'x1': round(float(x1), 2),
                'y0': round(float(y0), 2), 'y1': round(float(y1), 2),
                'source': text,
                'layout': _classify_pdf_block(text, x0, y0, x1, y1),
                'width': round(float(x1 - x0), 2), 'height': round(float(y1 - y0), 2),
            })
        # 按 y 坐标排序，保证段落顺序正确（页眉在前、正文居中、页脚在后）
        raw_blocks.sort(key=lambda b: b['y0'])
        result = []
        for legacy_index, block in enumerate(raw_blocks):
            if block['layout'] != 'table':
                lines = [line.strip() for line in block['source'].splitlines() if line.strip()]
                was_old_wide_table = len(lines) >= 4 and block['width'] > block['height'] * 4
                # Do not reuse an old cache entry if its source used to be
                # flattened as a table row by the previous renderer.
                block['cache_key'] = (
                    f"text-v2:{page_num}:{legacy_index}" if was_old_wide_table
                    else f"{page_num}:{legacy_index}"
                )
                result.append(block)
                continue

            # A table block is expanded into real PyMuPDF text spans. This
            # preserves the original columns, rules, values and units.
            match = min(
                dict_blocks,
                key=lambda candidate: sum(
                    abs(float(candidate['bbox'][n]) - block[key])
                    for n, key in enumerate(('x0', 'y0', 'x1', 'y1'))
                ),
                default=None,
            )
            line_starts = [round(float(line['bbox'][0]) / 5) * 5 for line in (match or {}).get('lines', [])]
            repeated_columns = sum(line_starts.count(start) >= 2 for start in set(line_starts))
            # Header bands and the last few parameter rows often have only
            # one occurrence of each column.  They are still tables: keeping
            # them as one paragraph makes the Chinese shrink across every
            # column and destroys the original grid.  Recognise the stable
            # data-sheet vocabulary and split its real spans just like a
            # regular multi-row table.
            table_header_or_row = bool(re.search(
                r"\b(?:Symbol|Parameter|Conditions|Units|Typ|Guaranteed\s+Limits|"
                r"Maximum\s+(?:Input|Quiescent)|Supply\s+Current|"
                r"IIN|ICC|VIH|VIL|VOH|VOL|tPHL|tPLH|CIN|CPD)\b",
                block['source'],
                re.I,
            ))
            if match is None or (repeated_columns < 3 and not table_header_or_row):
                # Wide multi-column prose can look table-like in plain-text
                # extraction. Keep it as a paragraph instead of splitting
                # every word, and use a new key to discard its old flat cache.
                block['layout'] = 'paragraph'
                block['cache_key'] = f"text-v2:{page_num}:{legacy_index}"
                result.append(block)
                continue
            # Superscripts/subscripts (for example the ``CC`` in ``VCC``)
            # are emitted as separate PDF lines a couple of points away from
            # their base text.  Cluster nearby baselines before grouping spans
            # so the replacement box masks the whole technical label.
            rows = []
            for line in match.get('lines', []):
                for span in line.get('spans', []):
                    y0 = round(float(span['bbox'][1]), 1)
                    if rows and abs(y0 - rows[-1]['y0']) <= 3.2:
                        rows[-1]['spans'].append(span)
                    else:
                        rows.append({'y0': y0, 'spans': [span]})
            for row_index, row in enumerate(rows):
                spans = row['spans']
                spans.sort(key=lambda item: float(item['bbox'][0]))
                groups, current = [], []
                for span in spans:
                    span_text = ' '.join((span.get('text') or '').split())
                    current_text = ' '.join(
                        ' '.join((item.get('text') or '').split()) for item in current
                    )
                    gap = float(span['bbox'][0]) - float(current[-1]['bbox'][2]) if current else 0
                    # A circuit symbol and its prose label can share a PDF
                    # baseline with only a tiny gap (for example, ``tTLH``
                    # followed by ``Maximum Output Rise``).  They are two
                    # visual cells, not one translation target.
                    split_signal_from_label = (
                        bool(current)
                        and _looks_like_table_signal(current_text)
                        and _should_translate_table_span(span_text)
                    )
                    if current and (gap > 8 or split_signal_from_label):
                        groups.append(current)
                        current = []
                    current.append(span)
                if current:
                    groups.append(current)
                for group_index, group in enumerate(groups):
                    pieces = [' '.join((item.get('text') or '').split()) for item in group]
                    text = ' '.join(piece for piece in pieces if piece).strip()
                    if not _should_translate_table_span(text):
                        continue
                    x0 = min(float(item['bbox'][0]) for item in group)
                    y0 = min(float(item['bbox'][1]) for item in group)
                    x1 = max(float(item['bbox'][2]) for item in group)
                    y1 = max(float(item['bbox'][3]) for item in group)
                    result.append({
                        'x0': round(x0, 2), 'x1': round(x1, 2),
                        'y0': round(y0, 2), 'y1': round(y1, 2),
                        'source': text,
                        'layout': 'table_cell',
                        'width': round(x1 - x0, 2), 'height': round(y1 - y0, 2),
                        'cache_key': f"table-{PDF_SEGMENT_CACHE_VERSION}:{page_num}:{legacy_index}:{row_index}:{group_index}:{hashlib.sha1(text.encode('utf-8')).hexdigest()[:12]}",
                    })
        return _merge_pdf_heading_parts(result, page_num)
    finally:
        doc.close()


@app.post("/api/pdf-page-translate/{book_id}")
async def translate_pdf_page(book_id: str, req: dict):
    """Extract a PDF page's text and translate it to Chinese via AI (with disk cache)."""
    import fitz
    safe_id = os.path.basename(book_id)
    book_dir = os.path.join(BOOKS_DIR, safe_id)
    pdf_path = os.path.join(book_dir, "book.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    try:
        page_num = int(req.get("page", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid page number")

    # 1. 命中本地缓存则直接返回，不重复翻译
    cache = _load_translation_cache(book_dir)
    key = str(page_num)
    cached = cache.get(key)
    if cached:
        return {"page": page_num, "translation": cached, "cached": True}

    def _extract():
        doc = fitz.open(pdf_path)
        try:
            if page_num < 1 or page_num > len(doc):
                return None
            page = doc[page_num - 1]
            text = page.get_text("text").strip()
            return text
        finally:
            doc.close()

    text = await asyncio.to_thread(_extract)
    if text is None:
        return {"page": page_num, "translation": "", "error": "page out of range"}
    if not text:
        return {"page": page_num, "translation": "", "error": "no extractable text (scanned page?)"}

    prompt = f"""请将以下英文技术文档内容完整翻译成中文。

翻译要求：
- 准确传达原意，术语保持专业（寄存器、引脚、命令等保留英文缩写或附注原文）
- 保留数字、寄存器名、信号名、命令码（如 0x03、CS#、SCLK、WREN 等）
- 保留换行与段落结构，便于对照阅读
- 直接输出译文，不要思考过程、不要推理、不要解释、不要加任何前缀或后缀

原文：
{text[:12000]}"""

    try:
        result, _ = await _ai_complete(prompt, temperature=0.1, max_tokens=16384, task='translate')
        translation = (result or "").strip()
        if translation:
            # 2. 写入磁盘缓存（加锁，避免并发读改写互相覆盖）
            with _translation_lock:
                latest = _load_translation_cache(book_dir)
                latest[key] = translation
                _save_translation_cache(book_dir, latest)
        return {"page": page_num, "translation": translation, "cached": False}
    except Exception as e:
        return {"page": page_num, "translation": "", "error": str(e)}


@app.post("/api/pdf-segments/{book_id}")
async def translate_pdf_segments(book_id: str, req: dict):
    """逐段提取某页文本并翻译，返回段落级数据（含位置坐标），支持块级缓存。"""
    import fitz
    safe_id = os.path.basename(book_id)
    book_dir = os.path.join(BOOKS_DIR, safe_id)
    pdf_path = os.path.join(book_dir, "book.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    try:
        page_num = int(req.get("page", 1))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid page number")

    blocks = await asyncio.to_thread(_extract_pdf_blocks, pdf_path, page_num)
    if blocks is None:
        return {"page": page_num, "segments": [], "error": "page out of range"}
    if not blocks:
        return {"page": page_num, "segments": [], "error": "no extractable text"}

    cache = _load_segment_cache(book_dir)
    segments = []
    pending = []  # (index, block)
    for i, b in enumerate(blocks):
        key = b['cache_key']
        cached = cache.get(key)
        if cached:
            segments.append({
                'x0': b['x0'], 'x1': b['x1'], 'y0': b['y0'], 'y1': b['y1'],
                'source': b['source'], 'target': _normalise_segment_translation(cached, b['layout']),
                'layout': b['layout'],
            })
        else:
            segments.append({
                'x0': b['x0'], 'x1': b['x1'], 'y0': b['y0'], 'y1': b['y1'],
                'source': b['source'], 'target': None, 'layout': b['layout'],
            })
            # ``segments`` omits intentionally untranslated cells, so its
            # index is not the original ``blocks`` index.
            pending.append((len(segments) - 1, b))

    # 并发翻译未缓存的块（限并发 4，逐块翻译保证段落严格对齐）
    if pending:
        sem = asyncio.Semaphore(4)

        async def _translate_one(segment_index, b):
            if b['layout'] == 'table_cell':
                calibrated = _calibrated_table_cell_translation(b['source'])
                if calibrated:
                    return segment_index, b, calibrated
            async with sem:
                try:
                    result, _ = await _ai_complete(
                        _segment_translation_prompt(b), temperature=0.1, max_tokens=4096, task='translate'
                    )
                    return segment_index, b, _normalise_segment_translation(result or '', b['layout'])
                except Exception as e:
                    print(f"[segments] segment {segment_index} translate failed: {e}")
                    return segment_index, b, ''

        results = await asyncio.gather(*[_translate_one(i, b) for i, b in pending])

        # 写回缓存
        with _translation_lock:
            latest = _load_segment_cache(book_dir)
            for segment_index, block, target in results:
                if target:
                    latest[block['cache_key']] = target
                    segments[segment_index]['target'] = target
            _save_segment_cache(book_dir, latest)

    # 过滤掉翻译失败的块
    segments = [s for s in segments if s.get('target')]
    return {"page": page_num, "segments": segments}


@app.get("/api/pdf-chat/{book_id}")
async def get_pdf_chat(book_id: str):
    """读取某本书的 AI 对话记录（持久化到文件夹）。"""
    safe_id = os.path.basename(book_id)
    book_dir = os.path.join(BOOKS_DIR, safe_id)
    path = _chat_history_path(book_dir)
    if os.path.exists(path):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"sessions": [], "activeId": 0}


@app.post("/api/pdf-chat/{book_id}")
async def save_pdf_chat(book_id: str, req: dict):
    """保存某本书的 AI 对话记录到文件夹。"""
    safe_id = os.path.basename(book_id)
    book_dir = os.path.join(BOOKS_DIR, safe_id)
    if not os.path.isdir(book_dir):
        raise HTTPException(status_code=404, detail="Book not found")
    path = _chat_history_path(book_dir)
    try:
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(req, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True}


@app.post("/api/pdf-search/{book_id}")
async def search_pdf(book_id: str, req: dict):
    """Search text in PDF file using PyMuPDF."""
    import fitz
    safe_id = os.path.basename(book_id)
    pdf_path = os.path.join(BOOKS_DIR, safe_id, "book.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF file not found")

    query = (req.get("query") or "").strip()
    if not query:
        return {"results": []}

    results = []
    doc = fitz.open(pdf_path)
    try:
        for page_num in range(len(doc)):
            page = doc[page_num]
            text_instances = page.search_for(query)
            if text_instances:
                page_text = page.get_text("text")
                lower_text = page_text.lower()
                lower_query = query.lower()
                for rect in text_instances:
                    idx = lower_text.find(lower_query)
                    if idx >= 0:
                        start = max(0, idx - 40)
                        end = min(len(page_text), idx + len(query) + 40)
                        snippet = page_text[start:end].replace('\n', ' ').strip()
                        if start > 0:
                            snippet = '...' + snippet
                        if end < len(page_text):
                            snippet = snippet + '...'
                    else:
                        snippet = query
                    results.append({
                        "page": page_num + 1,
                        "snippet": snippet,
                        "rect": [rect.x0, rect.y0, rect.x1, rect.y1],
                    })
            if len(results) >= 200:
                break
    finally:
        doc.close()

    return {"results": results}


@app.post("/api/search-cover/{book_id}")
async def search_cover_online(book_id: str, req: dict = None):
    """Search for book cover online using Google Books + Douban."""
    safe_id = os.path.basename(book_id)

    # Try EPUB first, then PDF meta.json
    book = load_book_cached(safe_id)
    meta_path = os.path.join(BOOKS_DIR, safe_id, "meta.json")
    if not book and not os.path.exists(meta_path):
        raise HTTPException(status_code=404, detail="Book not found")

    # Allow custom query from user
    custom_query = (req or {}).get("query", "").strip()

    if custom_query:
        query = custom_query
    elif book:
        title = book.metadata.title
        authors = ', '.join(book.metadata.authors) if book.metadata.authors else ''
        query = f"{title} {authors}".strip()
    else:
        with open(meta_path, encoding='utf-8') as f:
            pdf_meta = json.load(f)
        query = f"{pdf_meta.get('title', '')} {pdf_meta.get('author', '')}".strip()

    import urllib.parse
    import urllib.request

    # Detect if query is likely Chinese
    has_cjk = any('\u4e00' <= ch <= '\u9fff' for ch in query)
    douban_covers = []
    google_covers = []

    # --- Douban (better for Chinese books) ---
    try:
        dquery = custom_query if custom_query else (
            _re.sub(r'[\\/:*?"<>|]', '', book.metadata.title).strip() if book else
            _re.sub(r'[\\/:*?"<>|]', '', query).strip()
        )
        durl = f"https://book.douban.com/j/subject_suggest?q={urllib.parse.quote(dquery)}"
        def _fetch_douban():
            req = urllib.request.Request(durl, headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://book.douban.com/",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read())
        items = await asyncio.to_thread(_fetch_douban)
        for item in items[:6]:
            pic = item.get("pic", "")
            if pic:
                img_url = pic.replace("/s/", "/l/")
                douban_covers.append({
                    "title": item.get("title", ""),
                    "authors": [item["author_name"]] if item.get("author_name") else [],
                    "image_url": img_url,
                    "source": "douban",
                })
    except Exception:
        pass

    # --- Google Books ---
    try:
        gurl = f"https://www.googleapis.com/books/v1/volumes?q={urllib.parse.quote(query)}&maxResults=12"
        def _fetch_google():
            req = urllib.request.Request(gurl, headers={"User-Agent": "FixedPDF/1.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read())
        data = await asyncio.to_thread(_fetch_google)
        for item in data.get("items", []):
            info = item.get("volumeInfo", {})
            images = info.get("imageLinks", {})
            # Prefer highest resolution available
            img_url = (images.get("extraLarge") or images.get("large") or
                       images.get("medium") or images.get("thumbnail"))
            if img_url:
                img_url = img_url.replace("http://", "https://").replace("&edge=curl", "")
                # Request higher zoom level for better quality
                img_url = _re.sub(r'zoom=\d', 'zoom=3', img_url)
                google_covers.append({
                    "title": info.get("title", ""),
                    "authors": info.get("authors", []),
                    "image_url": img_url,
                })
    except Exception:
        pass

    # CJK queries: Douban first; otherwise Google first
    if has_cjk:
        covers = douban_covers + google_covers
    else:
        covers = google_covers + douban_covers

    return {"covers": covers, "query": query}


@app.get("/api/proxy-image")
async def proxy_image(url: str):
    """Proxy external images that block direct browser access (e.g. Douban)."""
    import urllib.request
    if "doubanio.com" not in url and "douban.com" not in url:
        raise HTTPException(status_code=400, detail="Only douban images supported")
    def _fetch():
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://book.douban.com/",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read(), resp.headers.get("Content-Type", "image/jpeg")
    try:
        data, ctype = await asyncio.to_thread(_fetch)
        return Response(content=data, media_type=ctype)
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch image")


@app.post("/api/set-cover/{book_id}")
async def set_cover_from_url(book_id: str, req: dict):
    """Download an image URL and set it as the book cover."""
    safe_id = os.path.basename(book_id)
    images_dir = os.path.join(BOOKS_DIR, safe_id, "images")
    os.makedirs(images_dir, exist_ok=True)

    image_url = req.get("image_url", "")
    if not image_url:
        raise HTTPException(status_code=400, detail="No image URL provided")

    import urllib.request
    try:
        def _download():
            headers = {"User-Agent": "Mozilla/5.0"}
            # Douban images require Referer header
            if "doubanio.com" in image_url:
                headers["Referer"] = "https://book.douban.com/"
            req_obj = urllib.request.Request(image_url, headers=headers)
            with urllib.request.urlopen(req_obj, timeout=10) as resp:
                return resp.read()
        img_data = await asyncio.to_thread(_download)

        # Auto-trim white borders
        import io

        from PIL import Image, ImageChops
        def _trim_and_save():
            img = Image.open(io.BytesIO(img_data)).convert("RGB")
            # Create a white background image, diff to find content area
            bg = Image.new("RGB", img.size, (255, 255, 255))
            diff = ImageChops.difference(img, bg)
            # Tolerance: treat near-white (>240) as white
            thresh = diff.point(lambda x: 0 if x < 15 else 255)
            bbox = thresh.getbbox()
            if bbox:
                # Only trim if it removes meaningful border (>2% per side)
                w, h = img.size
                margin = 0.02
                if (bbox[0] > w * margin or bbox[1] > h * margin
                        or bbox[2] < w * (1 - margin) or bbox[3] < h * (1 - margin)):
                    img = img.crop(bbox)
            img.save(cover_path, "JPEG", quality=92)

        cover_path = os.path.join(images_dir, "cover.jpg")
        await asyncio.to_thread(_trim_and_save)

        # Also write marker
        marker_path = os.path.join(BOOKS_DIR, safe_id, "cover_image.txt")
        with open(marker_path, "w") as f:
            f.write("cover.jpg")

        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download cover: {str(e)}")


def auto_import_default_books():
    """Scan assets/ for specific default EPUBs and import them if not already in library."""
    default_book = os.path.join(RESOURCE_DIR, "assets", "Meditations by Emperor of Rome Marcus Aurelius.epub")
    if not os.path.exists(default_book):
        return

    # Check if already imported (basic folder name check)
    book_filename = os.path.basename(default_book)
    book_id = os.path.splitext(book_filename)[0].replace(" ", "_") + "_data"
    book_data_path = os.path.join(BOOKS_DIR, book_id)

    if not os.path.exists(book_data_path):
        print(f"📦 First run detected: Auto-importing '{book_filename}'...")
        try:
            # Silence internal prints during auto-import
            import io
            import sys
            old_stdout = sys.stdout
            sys.stdout = io.StringIO()

            # 注意：必须传入独立的子目录，否则 process_epub 内部的 rmtree 会清空整个书库
            book = process_epub(default_book, book_data_path)
            save_to_pickle(book, book_data_path)

            sys.stdout = old_stdout
            print(f"✅ Successfully imported '{book_filename}'.")
        except Exception as e:
            print(f"❌ Failed to auto-import '{book_filename}': {e}")


if __name__ == "__main__":
    import uvicorn
    # Perform auto-import before starting server
    auto_import_default_books()
    uvicorn.run(app, host="127.0.0.1", port=8123)
