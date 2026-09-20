"""核对 requirements.txt 里的依赖是否都已装进当前解释器。

供 start.bat 调用：把「检查什么」和「安装什么」都收敛到 requirements.txt 这一个来源，
避免两边各维护一份清单后互相矛盾（曾经出现过检查 pillow、却怎么也装不上 pillow 的死循环）。

用法：
    python tools/check_deps.py [requirements.txt 路径]

输出约定（start.bat 依赖该约定解析）：
    依赖齐全时标准输出为空，退出码 0；
    有缺失时用一行、空格分隔的发行包名列出缺失项，退出码 1；
    清单文件读不到时退出码 2。

只校验「装没装」，不比对版本号：调用方在发现缺失后会照着同一份清单重装，
在这里强行比对版本反而会把「已装新版本、满足 >= 约束」的环境误判成缺失。
"""
from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

DEFAULT_REQUIREMENTS = Path(__file__).resolve().parent.parent / 'requirements.txt'

# requirement 行的开头：发行包名（不含 extras 与版本约束）
_PACKAGE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*')


def parse_package_name(line):
    """从一行 requirement 中取出发行包名；注释、空行、无效行返回 None。"""
    line = line.split('#', 1)[0].strip()
    if not line or line.startswith('-'):
        return None
    match = _PACKAGE_NAME.match(line)
    return match.group(0) if match else None


def required_packages(text):
    """按出现顺序解析清单，返回去重后的发行包名列表。"""
    names = []
    for line in text.splitlines():
        name = parse_package_name(line)
        if name and name not in names:
            names.append(name)
    return names


def missing_packages(text):
    """返回清单中尚未安装的发行包名。"""
    missing = []
    for name in required_packages(text):
        try:
            metadata.version(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
    return missing


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    requirements = Path(args[0]) if args else DEFAULT_REQUIREMENTS

    try:
        text = requirements.read_text(encoding='utf-8')
    except OSError as exc:
        print(f'无法读取依赖清单 {requirements}：{exc}', file=sys.stderr)
        return 2

    missing = missing_packages(text)
    if missing:
        print(' '.join(missing))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
