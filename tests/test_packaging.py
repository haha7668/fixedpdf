"""依赖清单一致性：requirements.txt 必须覆盖 pyproject.toml 声明的运行时依赖。

requirements.txt 是终端用户（双击 start.bat）的安装来源，pyproject.toml + uv.lock 是
CI 与开发者的来源。两者一旦脱节就会造成双击启动的硬阻塞：检查说缺某个包，脚本却只能
照着 requirements.txt 装，于是永远补不上（真实案例：requirements.txt 少了 pillow）。
CI 走的是 uv sync，读不到 requirements.txt，所以这条一致性只能由测试来守护。
"""
import importlib.util
import re
from importlib import metadata
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 没有 tomllib，用 tomli 兜底
    import tomli as tomllib

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / 'requirements.txt'
PYPROJECT = ROOT / 'pyproject.toml'
CHECK_DEPS_HELPER = ROOT / 'tools' / 'check_deps.py'

_PACKAGE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*')


def canonical(name):
    """按 PEP 503 归一化发行包名（下划线、点、连字符视为等价）。"""
    return re.sub(r'[-_.]+', '-', name).lower()


def requirement_names(text):
    """从 requirements.txt 文本中取出归一化后的发行包名。"""
    names = set()
    for line in text.splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        match = _PACKAGE_NAME.match(line)
        if match:
            names.add(canonical(match.group(0)))
    return names


def declared_dependencies():
    """pyproject.toml 中 [project] dependencies 声明的包名（归一化后）。"""
    project = tomllib.loads(PYPROJECT.read_text(encoding='utf-8'))['project']
    names = set()
    for spec in project['dependencies']:
        match = _PACKAGE_NAME.match(spec.strip())
        assert match, f'无法解析依赖声明：{spec}'
        names.add(canonical(match.group(0)))
    return names


def load_check_deps():
    """按路径加载 tools/check_deps.py（tools 不是包，只能走 importlib）。"""
    spec = importlib.util.spec_from_file_location('check_deps', CHECK_DEPS_HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def locked_package_names():
    """uv.lock 中记录的全部包名（归一化后）。"""
    lock = tomllib.loads((ROOT / 'uv.lock').read_text(encoding='utf-8'))
    return {canonical(package['name']) for package in lock['package']}


def test_requirements_covers_declared_dependencies():
    pinned = requirement_names(REQUIREMENTS.read_text(encoding='utf-8'))
    missing = sorted(declared_dependencies() - pinned)
    assert not missing, (
        f'requirements.txt 缺少 pyproject.toml 声明的依赖：{missing}。'
        'start.bat 只会照着 requirements.txt 安装，漏项会让用户双击后卡在依赖不完整。'
    )


def test_requirements_entries_are_known_to_uv_lock():
    pinned = requirement_names(REQUIREMENTS.read_text(encoding='utf-8'))
    unknown = sorted(pinned - locked_package_names())
    assert not unknown, (
        f'requirements.txt 中的 {unknown} 不在 uv.lock 里。'
        '这类条目要么已无人依赖（lxml、six 就是 EbookLib 时代的陈迹，应删除），'
        '要么是新依赖但没写进 pyproject.toml（应先在 pyproject 声明，再由 uv lock 生成）。'
    )


def test_start_helper_parses_same_package_names():
    text = REQUIREMENTS.read_text(encoding='utf-8')
    from_helper = {canonical(name) for name in load_check_deps().required_packages(text)}
    assert from_helper == requirement_names(text)


def test_parse_package_name_ignores_comments_extras_and_options():
    helper = load_check_deps()
    assert helper.parse_package_name('pillow==12.2.0') == 'pillow'
    assert helper.parse_package_name('pymupdf>=1.28.2') == 'pymupdf'
    assert helper.parse_package_name('httpx[socks]>=0.28.1') == 'httpx'
    assert helper.parse_package_name('pillow==12.2.0  # 封面裁剪') == 'pillow'
    assert helper.parse_package_name('') is None
    assert helper.parse_package_name('   ') is None
    assert helper.parse_package_name('-r requirements-dev.txt') is None


def test_missing_packages_reports_only_uninstalled(monkeypatch):
    helper = load_check_deps()

    def fake_version(name):
        if canonical(name) == 'pillow':
            raise metadata.PackageNotFoundError(name)
        return '1.0'

    monkeypatch.setattr(helper.metadata, 'version', fake_version)
    assert helper.missing_packages('httpx==0.28.1\npillow==12.2.0\n') == ['pillow']


def test_main_prints_missing_names_on_one_line(monkeypatch, capsys, tmp_path):
    helper = load_check_deps()
    monkeypatch.setattr(helper, 'missing_packages', lambda _text: ['aiohttp', 'pillow'])
    manifest = tmp_path / 'requirements.txt'
    manifest.write_text('aiohttp==3.13.3\npillow==12.2.0\n', encoding='utf-8')
    assert helper.main([str(manifest)]) == 1
    assert capsys.readouterr().out.strip() == 'aiohttp pillow'


def test_main_stays_silent_when_everything_installed(monkeypatch, capsys, tmp_path):
    helper = load_check_deps()
    monkeypatch.setattr(helper, 'missing_packages', lambda _text: [])
    manifest = tmp_path / 'requirements.txt'
    manifest.write_text('pillow==12.2.0\n', encoding='utf-8')
    assert helper.main([str(manifest)]) == 0
    # start.bat 用 set /p 读取输出，依赖齐全时必须是空输出
    assert capsys.readouterr().out == ''


def test_main_returns_two_when_manifest_unreadable(capsys, tmp_path):
    helper = load_check_deps()
    assert helper.main([str(tmp_path / 'nope.txt')]) == 2
    assert '无法读取依赖清单' in capsys.readouterr().err
