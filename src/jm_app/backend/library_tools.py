"""Small, dependency-free replacements for JMComic-qt's auxiliary tools."""

from __future__ import annotations

import shutil
import shlex
import subprocess
from pathlib import Path
from typing import Iterable, List
from urllib.parse import quote

import requests
from PIL import Image


DEFAULT_DOH_ENDPOINT = "https://parse.jpacg.cc/parse"
_SHELL_LAUNCHERS = {"cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}


def query_doh(domain: str, endpoint: str = DEFAULT_DOH_ENDPOINT) -> List[dict]:
    domain = str(domain or "").strip().strip(".")
    if not domain:
        raise ValueError("请输入要查询的域名")
    response = requests.get(
        endpoint.strip() or DEFAULT_DOH_ENDPOINT,
        params={"name": domain, "type": "A"},
        headers={"Accept": "application/dns-json"},
        timeout=(6, 15),
    )
    response.raise_for_status()
    payload = response.json()
    answers = payload.get("Answer") or []
    return [
        {
            "name": str(item.get("name") or domain),
            "type": int(item.get("type") or 0),
            "ttl": int(item.get("TTL") or 0),
            "data": str(item.get("data") or ""),
        }
        for item in answers
        if isinstance(item, dict)
    ]


def upscale_images(paths: Iterable[Path], output_dir: Path, scale: int = 2) -> List[Path]:
    """Lanczos batch resize used when an external SR engine is unavailable."""
    scale = max(1, min(int(scale), 4))
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    for source in [Path(path) for path in paths]:
        if not source.is_file():
            continue
        try:
            with Image.open(source) as image:
                image.load()
                width, height = image.size
                if width < 1 or height < 1:
                    continue
                resized = image.resize((width * scale, height * scale), Image.Resampling.LANCZOS)
                suffix = source.suffix.lower() if source.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".png"
                target = output_dir / f"{source.stem}_{scale}x{suffix}"
                if suffix in {".jpg", ".jpeg"} and resized.mode not in {"RGB", "L"}:
                    resized = resized.convert("RGB")
                resized.save(target)
                outputs.append(target)
        except Exception:
            continue
    if not outputs:
        raise ValueError("没有可处理的图片")
    return outputs


def _external_command_arguments(
    command_template: str, source: Path, target: Path
) -> List[str]:
    try:
        tokens = shlex.split(command_template, posix=False)
    except ValueError as exc:
        raise ValueError(f"外部超分命令格式无效：{exc}") from exc
    tokens = [
        token[1:-1]
        if len(token) >= 2 and token[0] == token[-1] and token[0] in {"\"", "'"}
        else token
        for token in tokens
    ]
    if not tokens:
        raise ValueError("外部超分命令不能为空")
    if tokens[0].casefold() in _SHELL_LAUNCHERS:
        raise ValueError("外部超分命令不能通过命令解释器启动")

    executable = Path(tokens[0]).expanduser()
    if executable.is_absolute() or any(separator in tokens[0] for separator in ("/", "\\")):
        if not executable.is_file():
            raise ValueError(f"找不到外部超分程序：{tokens[0]}")
        tokens[0] = str(executable)
    elif shutil.which(tokens[0]) is None:
        raise ValueError(f"找不到外部超分程序：{tokens[0]}")

    return [
        token.replace("{input}", str(source)).replace("{output}", str(target))
        for token in tokens
    ]


def run_external_super_resolution(paths: Iterable[Path], output_dir: Path, command_template: str) -> List[Path]:
    """Run a configured waifu2x/Real-ESRGAN compatible command per image.

    The template must contain ``{input}`` and ``{output}``.  This makes the
    old optional native super-resolution feature usable without bundling a GPU
    executable or silently replacing an AI model with a different algorithm.
    """
    command_template = str(command_template or "").strip()
    if "{input}" not in command_template or "{output}" not in command_template:
        raise ValueError("外部超分命令必须包含 {input} 与 {output} 占位符")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    for source in [Path(path) for path in paths]:
        if not source.is_file():
            continue
        target = output_dir / f"{source.stem}_sr{source.suffix or '.png'}"
        command = _external_command_arguments(command_template, source, target)
        result = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "外部超分命令失败").strip()
            raise RuntimeError(message[-1600:])
        if not target.exists():
            raise RuntimeError(f"外部超分未生成输出文件：{target}")
        outputs.append(target)
    if not outputs:
        raise ValueError("没有可处理的图片")
    return outputs


def _iter_files(source: Path):
    if source.is_file():
        yield source, Path(source.name)
        return
    if not source.is_dir():
        raise ValueError(f"找不到待上传文件：{source}")
    for path in source.rglob("*"):
        if path.is_file():
            yield path, path.relative_to(source)


def copy_to_storage(source: Path, destination: Path) -> List[Path]:
    """Upload to a local path or an already mounted SMB/SMB3 share."""
    source = Path(source).expanduser()
    destination = Path(destination).expanduser()
    outputs: List[Path] = []
    for path, relative in _iter_files(source):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        outputs.append(target)
    return outputs


def upload_webdav(source: Path, base_url: str, remote_path: str = "", username: str = "", password: str = "") -> int:
    """Upload a file tree using standard WebDAV MKCOL/PUT requests."""
    base = str(base_url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        raise ValueError("WebDAV 地址必须以 http:// 或 https:// 开头")
    root = str(remote_path or "").strip("/")
    session = requests.Session()
    if username:
        session.auth = (username, password)
    uploaded = 0
    created = set()
    for path, relative in _iter_files(Path(source).expanduser()):
        remote_parts = ([part for part in root.split("/") if part] + list(relative.parts))
        for index in range(1, len(remote_parts)):
            directory = "/".join(quote(part) for part in remote_parts[:index])
            if directory in created:
                continue
            response = session.request("MKCOL", f"{base}/{directory}", timeout=(6, 20))
            if response.status_code not in {200, 201, 204, 301, 405}:
                response.raise_for_status()
            created.add(directory)
        target = f"{base}/{'/'.join(quote(part) for part in remote_parts)}"
        with path.open("rb") as handle:
            response = session.put(target, data=handle, timeout=(8, 90))
            response.raise_for_status()
        uploaded += 1
    return uploaded
