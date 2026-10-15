from __future__ import annotations

import copy
import hashlib
import re
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

from PySide6.QtCore import QThread, Signal

from ..backend.pdf_utils import IMAGE_SUFFIXES, collect_images, collect_images_recursive
from ..backend.runtime_paths import local_zip_cache_dir
from ..frontend.hd_reader import collect_reader_files


def collect_local_reader_images_for_cache(directory: Path) -> List[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    try:
        direct = collect_images(directory)
    except OSError:
        direct = []
    if direct:
        return direct
    try:
        return sorted(
            path
            for path in directory.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        )
    except OSError:
        return []


def extract_zip_images_to_reader_cache(archive_path: Path) -> Path:
    """Extract image members from a local archive into the reader cache safely."""
    archive_path = archive_path.expanduser().resolve(strict=True)
    stat = archive_path.stat()
    key = f"{archive_path}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    destination = local_zip_cache_dir() / hashlib.sha256(key).hexdigest()[:24]
    if destination.exists() and collect_local_reader_images_for_cache(destination):
        return destination

    max_members = 10000
    max_total_size = 2 * 1024 * 1024 * 1024
    total_size = 0
    extracted = 0
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) > max_members:
            raise ValueError("ZIP contains too many entries")
        for member in members:
            if member.is_dir():
                continue
            member_path = PurePosixPath(member.filename.replace("\\", "/"))
            parts = [part for part in member_path.parts if part not in {"", "."}]
            if member_path.is_absolute() or ".." in parts or not parts:
                continue
            if Path(parts[-1]).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            total_size += max(0, int(member.file_size))
            if total_size > max_total_size:
                raise ValueError("ZIP uncompressed size is too large")
            target = destination.joinpath(*parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            extracted += 1
    if not extracted:
        raise ValueError("ZIP does not contain readable images")
    return destination


def history_cover_cache_key_from_record(record: Dict[str, str]) -> str:
    values = [
        str(record.get("album_id") or record.get("id") or ""),
        str(record.get("path") or ""),
        str(record.get("pdf_path") or ""),
        str(record.get("image_dir") or ""),
    ]
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        values.extend(str(value) for value in outputs)
    return "|".join(values)


def find_history_local_cover_path(record: Dict[str, str]) -> Optional[Path]:
    paths: List[Path] = []
    for key in ("cover_path", "local_cover", "thumbnail", "image_dir", "path", "pdf_path"):
        value = record.get(key)
        if value:
            paths.append(Path(str(value)).expanduser())
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        for value in outputs:
            if value:
                paths.append(Path(str(value)).expanduser())

    candidates: List[Path] = []
    for path in paths:
        try:
            if path.suffix.lower() in IMAGE_SUFFIXES and path.exists():
                return path
            if path.is_dir():
                candidates.append(path)
            elif path.suffix.lower() == ".pdf":
                candidates.append(path.with_suffix(""))
        except OSError:
            continue
    for directory in candidates:
        try:
            if not directory.exists() or not directory.is_dir():
                continue
            images = collect_images(directory) or collect_images_recursive(directory)
        except OSError:
            images = []
        if images:
            return images[0]
    return None


def local_chapter_sort_key_value(text: str):
    parts = re.split(r"(\d+)", text or "")
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def normalized_local_path(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False)).lower()
    except Exception:
        return str(path).lower()


def directory_may_contain_reader_images_path(directory: Path) -> bool:
    try:
        for child in directory.iterdir():
            if child.is_file() and child.suffix.lower() in IMAGE_SUFFIXES:
                return True
        for child in directory.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            for item in child.iterdir():
                if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES:
                    return True
    except OSError:
        return False
    return False


def local_reader_chapter_dir_groups_for_path(image_dir: Optional[Path]) -> List[tuple[str, Path, str]]:
    if image_dir is None or not image_dir.exists() or not image_dir.is_dir():
        return []
    if collect_images(image_dir):
        return [(image_dir.name, image_dir, str(image_dir))]
    try:
        child_dirs = [
            child
            for child in sorted(image_dir.iterdir(), key=lambda path: local_chapter_sort_key_value(path.name))
            if child.is_dir() and not child.name.startswith(".")
        ]
    except OSError:
        return []
    groups = [
        (child.name, child, str(child))
        for child in child_dirs
        if directory_may_contain_reader_images_path(child)
    ]
    return groups or [(image_dir.name, image_dir, str(image_dir))]


def local_reader_pdf_chapter_groups_from_record(record: Dict[str, str]) -> List[tuple[str, Path, str]]:
    candidates: List[Path] = []
    for key in ("pdf_path", "path"):
        value = record.get(key) or ""
        if value:
            candidates.append(Path(value).expanduser())
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())

    pdfs: List[Path] = []
    seen = set()
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.suffix.lower() == ".pdf" and candidate.stat().st_size > 0:
                paths = [candidate]
            elif candidate.is_dir():
                paths = sorted(
                    path
                    for path in candidate.iterdir()
                    if path.is_file() and path.suffix.lower() == ".pdf" and path.stat().st_size > 0
                )
            else:
                paths = []
        except OSError:
            paths = []
        for path in paths:
            key = normalized_local_path(path)
            if key in seen:
                continue
            seen.add(key)
            pdfs.append(path)

    pdfs.sort(key=lambda path: local_chapter_sort_key_value(path.stem))
    return [(path.stem, path, str(path)) for path in pdfs]


def resolve_history_image_dir_from_path(path: Path) -> Optional[Path]:
    if path.is_dir() and directory_may_contain_reader_images_path(path):
        return path
    if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
        return path.parent
    if path.is_file() and path.suffix.lower() in {".pdf", ".zip"}:
        sibling = path.with_suffix("")
        if sibling.exists() and sibling.is_dir() and directory_may_contain_reader_images_path(sibling):
            return sibling
    return None


def history_record_search_tokens_for_reader(record: Dict[str, str]) -> List[str]:
    values = [
        str(record.get("album_id") or record.get("id") or ""),
        str(record.get("title") or ""),
        Path(str(record.get("file") or "")).stem,
        Path(str(record.get("path") or "")).stem,
        Path(str(record.get("pdf_path") or "")).stem,
    ]
    tokens: List[str] = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        tokens.append(value)
        match = re.search(r"(\d{4,})", value)
        if match:
            tokens.append(match.group(1))
            tokens.append(f"JM{match.group(1)}")
    return list(dict.fromkeys(token.lower() for token in tokens if token.strip()))


def unique_existing_reader_dirs(roots: List[Path]) -> List[Path]:
    unique: List[Path] = []
    seen = set()
    for root in roots:
        try:
            if not root.exists() or not root.is_dir():
                continue
            key = normalized_local_path(root)
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def matching_history_image_dirs_for_reader(root: Path, tokens: List[str]) -> List[Path]:
    if not tokens or not root.exists() or not root.is_dir():
        return []
    try:
        candidates = [root] + [child for child in root.iterdir() if child.is_dir()]
    except OSError:
        return []
    matches: List[Path] = []
    for candidate in candidates:
        name = candidate.name.lower()
        if tokens and not any(token in name for token in tokens):
            continue
        if collect_local_reader_images_for_cache(candidate):
            matches.append(candidate)
    return sorted(matches, key=lambda path: len(path.parts))


def find_history_image_dir_for_reader(record: Dict[str, str], output_dir: Path, default_output_dir: Path) -> Optional[Path]:
    roots: List[Path] = []
    texts = [
        str(record.get("path") or ""),
        str(record.get("pdf_path") or ""),
        str(record.get("image_dir") or ""),
    ]
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        texts.extend(str(value) for value in outputs if str(value).strip())

    for text in texts:
        if not text.strip():
            continue
        path = Path(text).expanduser()
        base = path if path.is_dir() else path.parent
        roots.extend([base, base.parent])
    roots.extend([output_dir, default_output_dir])

    tokens = history_record_search_tokens_for_reader(record)
    for root in unique_existing_reader_dirs(roots):
        for candidate in matching_history_image_dirs_for_reader(root, tokens):
            return candidate
    return None


def resolve_history_image_dir_from_record_for_reader(record: Dict[str, str], output_dir: Path, default_output_dir: Path) -> Optional[Path]:
    image_dir = record.get("image_dir") or ""
    if image_dir:
        candidate = Path(image_dir).expanduser()
        if candidate.exists() and candidate.is_dir() and directory_may_contain_reader_images_path(candidate):
            return candidate
    for key in ("path", "pdf_path"):
        value = record.get(key) or ""
        if value:
            candidate = resolve_history_image_dir_from_path(Path(value).expanduser())
            if candidate:
                return candidate
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        for value in outputs:
            if str(value).strip():
                candidate = resolve_history_image_dir_from_path(Path(str(value)).expanduser())
                if candidate:
                    return candidate
    return find_history_image_dir_for_reader(record, output_dir, default_output_dir)


def resolve_history_zip_path_from_record(record: Dict[str, str]) -> Optional[Path]:
    candidates: List[Path] = []
    for key in ("path", "image_dir", "pdf_path"):
        value = record.get(key) or ""
        if value:
            candidates.append(Path(value).expanduser())
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.suffix.lower() == ".zip" and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return None


def resolve_history_pdf_path_from_record(record: Dict[str, str]) -> Optional[Path]:
    pdf_groups = local_reader_pdf_chapter_groups_from_record(record)
    if pdf_groups:
        return pdf_groups[0][1]
    candidates: List[Path] = []
    for key in ("pdf_path", "path"):
        value = record.get(key) or ""
        if value:
            candidates.append(Path(value).expanduser())
    outputs = record.get("outputs") or []
    if isinstance(outputs, list):
        candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.suffix.lower() == ".pdf" and candidate.stat().st_size > 0:
                return candidate
            if candidate.is_dir():
                _, pdf_path = collect_reader_files(candidate)
                if pdf_path is not None and pdf_path.stat().st_size > 0:
                    return pdf_path
        except OSError:
            continue
    return None


def prepare_local_history_reader_source(record: Dict[str, str], mode: str, output_dir: Path, default_output_dir: Path) -> Dict[str, object]:
    path_text = record.get("path", "") or record.get("pdf_path", "") or record.get("image_dir", "")
    path = Path(path_text).expanduser() if path_text else None
    image_dir = resolve_history_image_dir_from_record_for_reader(record, output_dir, default_output_dir)
    pdf_path = resolve_history_pdf_path_from_record(record)
    zip_path = resolve_history_zip_path_from_record(record)
    direct_images: List[Path] = []
    if path_text:
        candidate = Path(path_text).expanduser()
        try:
            if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES:
                direct_images = [candidate]
        except OSError:
            direct_images = []

    use_images = bool(image_dir or direct_images) and mode != "pdf"
    use_pdf = pdf_path is not None and (mode == "pdf" or not use_images)
    use_zip = zip_path is not None and mode != "pdf" and not use_images
    title = record.get("title") or (path.stem if path is not None else "本地阅读")
    restore_source = record.get("last_source") or ""

    if use_images:
        chapter_dirs = local_reader_chapter_dir_groups_for_path(image_dir) if image_dir else []
        if chapter_dirs:
            return {"kind": "chapter_dirs", "title": title, "chapter_dirs": chapter_dirs, "restore_source": restore_source}
        return {"kind": "images", "title": title, "images": direct_images}

    if use_zip and zip_path is not None:
        extracted_dir = extract_zip_images_to_reader_cache(zip_path)
        chapter_dirs = local_reader_chapter_dir_groups_for_path(extracted_dir)
        if chapter_dirs:
            return {"kind": "chapter_dirs", "title": title, "chapter_dirs": chapter_dirs, "restore_source": restore_source}
        return {"kind": "images", "title": title, "images": collect_local_reader_images_for_cache(extracted_dir)}

    if use_pdf and pdf_path is not None:
        pdf_groups = local_reader_pdf_chapter_groups_from_record(record)
        if len(pdf_groups) > 1:
            return {"kind": "pdf_groups", "title": title, "pdf_groups": pdf_groups, "restore_source": restore_source}
        return {"kind": "pdf", "title": title, "pdf_path": pdf_path}

    if path_text and path is not None and path.exists():
        return {"kind": "system", "title": title, "system_path": path}
    target = str(path) if path_text and path is not None else "历史记录中的本地文件"
    return {"kind": "missing", "title": title, "message": f"找不到可阅读的本地文件：{target}"}


class LocalHistorySyncWorker(QThread):
    synced = Signal(object, int, int)
    failed = Signal(str)

    def __init__(self, history: List[Dict[str, str]], roots: List[str], album_cache: Dict[str, Dict], parent=None):
        super().__init__(parent)
        self.history = copy.deepcopy(history)
        self.roots = [str(root) for root in roots if str(root).strip()]
        self.album_cache = copy.deepcopy(album_cache)

    def run(self):
        try:
            history, removed, added = self.sync_history()
            if not self.isInterruptionRequested():
                self.synced.emit(history, removed, added)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))

    def sync_history(self) -> tuple[List[Dict[str, str]], int, int]:
        kept = [record for record in self.history if self.history_record_has_local_file(record)]
        removed = len(self.history) - len(kept)
        added = 0
        for root in self.unique_existing_dirs([Path(value).expanduser() for value in self.roots]):
            for path in self.iter_completed_local_outputs(root):
                album_id = self.album_id_from_local_output(path)
                record = self.history_record_from_local_output(path, album_id, len(kept))
                if not record:
                    continue
                existing_index = self.find_history_index_for_album(kept, album_id) if album_id else -1
                if existing_index < 0:
                    existing_index = self.find_history_index_for_output(kept, path)
                if existing_index >= 0:
                    if self.merge_history_record(kept[existing_index], record):
                        added += 1
                    continue
                kept.append(record)
                added += 1
        return kept, removed, added

    @staticmethod
    def normalized_path(path: Path) -> str:
        try:
            return str(path.expanduser().resolve(strict=False)).lower()
        except Exception:
            return str(path).lower()

    @classmethod
    def unique_existing_dirs(cls, roots: List[Path]) -> List[Path]:
        unique: List[Path] = []
        seen = set()
        for root in roots:
            try:
                if not root.exists() or not root.is_dir():
                    continue
                key = cls.normalized_path(root)
            except OSError:
                continue
            if key in seen:
                continue
            seen.add(key)
            unique.append(root)
        return unique

    @staticmethod
    def local_chapter_sort_key(text: str):
        parts = re.split(r"(\d+)", str(text))
        return [int(part) if part.isdigit() else part.lower() for part in parts]

    @classmethod
    def collect_local_reader_images(cls, directory: Path) -> List[Path]:
        if not directory.exists() or not directory.is_dir():
            return []
        try:
            direct = collect_images(directory)
        except OSError:
            direct = []
        if direct:
            return direct
        try:
            return sorted(
                path
                for path in directory.rglob("*")
                if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
            )
        except OSError:
            return []

    @classmethod
    def direct_local_output_files(cls, directory: Path) -> List[Path]:
        if not directory.exists() or not directory.is_dir():
            return []
        try:
            return sorted(
                (
                    child
                    for child in directory.iterdir()
                    if child.is_file() and child.suffix.lower() in {".pdf", ".zip"} and child.stat().st_size > 0
                ),
                key=lambda path: cls.local_chapter_sort_key(path.name),
            )
        except OSError:
            return []

    @classmethod
    def is_completed_local_resource(cls, path: Path) -> bool:
        try:
            path = path.expanduser()
            if path.is_dir():
                return bool(directory_may_contain_reader_images_path(path) or cls.direct_local_output_files(path))
            if not path.is_file() or path.stat().st_size <= 0:
                return False
            return path.suffix.lower() in {".pdf", ".zip"} | IMAGE_SUFFIXES
        except Exception:
            return False

    @classmethod
    def is_local_album_output_dir(cls, directory: Path) -> bool:
        try:
            if collect_images(directory):
                return True
            direct_files = cls.direct_local_output_files(directory)
            if directory_may_contain_reader_images_path(directory) and direct_files:
                return True
            child_image_dirs = [
                child
                for child in directory.iterdir()
                if child.is_dir() and not child.name.startswith(".") and directory_may_contain_reader_images_path(child)
            ]
            if child_image_dirs and (
                cls.album_id_from_local_output(directory)
                or len(child_image_dirs) == 1
                or any(re.search(r"(^\d+|第.+[话話章]|chapter|chap|ch)", child.name, re.IGNORECASE) for child in child_image_dirs)
            ):
                return True
            return False
        except OSError:
            return False

    @classmethod
    def iter_completed_local_outputs(cls, root: Path) -> List[Path]:
        outputs: List[Path] = []
        seen = set()

        def add_output(path: Path):
            normalized = cls.normalized_path(path)
            if normalized not in seen:
                seen.add(normalized)
                outputs.append(path)

        def walk(directory: Path):
            try:
                children = sorted(
                    ((child.stat().st_mtime, child) for child in directory.iterdir()),
                    key=lambda item: item[0],
                    reverse=True,
                )
            except OSError:
                return
            for _mtime, child in children:
                if child.name.startswith("."):
                    continue
                if child.is_file():
                    if child.suffix.lower() in {".pdf", ".zip"} and cls.is_completed_local_resource(child):
                        add_output(child)
                    continue
                if not child.is_dir():
                    continue
                if cls.is_local_album_output_dir(child):
                    add_output(child)
                    continue
                walk(child)

        walk(root)
        return outputs

    @staticmethod
    def album_id_from_local_output(path: Path) -> str:
        match = re.search(r"(?:JM)?(\d{4,})", path.stem if path.is_file() else path.name, re.IGNORECASE)
        return match.group(1) if match else ""

    @classmethod
    def resolve_history_image_dir(cls, path: Path) -> Optional[Path]:
        try:
            path = path.expanduser()
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                return path.parent
            if path.is_dir() and directory_may_contain_reader_images_path(path):
                return path
            if path.is_file() and path.parent.exists():
                for candidate in sorted(path.parent.iterdir()):
                    if candidate.is_dir() and candidate.name.startswith(path.stem) and directory_may_contain_reader_images_path(candidate):
                        return candidate
                album_id_match = re.search(r"(\d+)", path.stem)
                if album_id_match:
                    album_id = album_id_match.group(1)
                    for candidate in sorted(path.parent.iterdir()):
                        if candidate.is_dir() and album_id in candidate.name and directory_may_contain_reader_images_path(candidate):
                            return candidate
        except OSError:
            return None
        return None

    def history_record_from_local_output(self, path: Path, album_id: str, sort_order: int, managed: bool = True) -> Optional[Dict[str, str]]:
        if not self.is_completed_local_resource(path):
            return None
        title = path.stem if path.is_file() else path.name
        if album_id:
            title = re.sub(rf"^JM?{re.escape(album_id)}[-_\s]*", "", title, flags=re.IGNORECASE) or title
        image_dir = self.resolve_history_image_dir(path)
        output_paths = [path]
        if path.is_dir():
            output_paths.extend(self.direct_local_output_files(path))
        pdf_candidates = [item for item in output_paths if item.is_file() and item.suffix.lower() == ".pdf"]
        album = self.album_cache.get(album_id) if album_id else None
        return {
            "title": str((album.get("title") if album else "") or title),
            "file": path.name,
            "path": str(path),
            "pdf_path": str(pdf_candidates[0]) if pdf_candidates else "",
            "image_dir": str(image_dir) if image_dir else (str(path) if path.is_dir() else ""),
            "album_id": album_id,
            "cover_url": str((album.get("cover_url") if album else "") or ""),
            "format": path.suffix.lstrip(".") if path.is_file() else "images",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "sort_order": str(sort_order),
            "managed": "1" if managed else "0",
            "outputs": [str(item) for item in output_paths],
        }

    @classmethod
    def history_record_local_paths(cls, record: Dict[str, str]) -> List[Path]:
        candidates: List[Path] = []
        for key in ("path", "pdf_path", "image_dir"):
            value = record.get(key) or ""
            if value:
                candidates.append(Path(value).expanduser())
        outputs = record.get("outputs") or []
        if isinstance(outputs, list):
            candidates.extend(Path(str(value)).expanduser() for value in outputs if str(value).strip())
        unique: List[Path] = []
        seen = set()
        for path in candidates:
            key = cls.normalized_path(path)
            if key in seen:
                continue
            seen.add(key)
            unique.append(path)
        return unique

    @classmethod
    def history_record_has_local_file(cls, record: Dict[str, str]) -> bool:
        return any(cls.is_completed_local_resource(path) for path in cls.history_record_local_paths(record))

    @classmethod
    def find_history_index_for_album(cls, history: List[Dict[str, str]], album_id: str) -> int:
        if not album_id:
            return -1
        for index, record in enumerate(history):
            if str(record.get("album_id") or record.get("id") or "") == str(album_id):
                return index
        return -1

    @classmethod
    def find_history_index_for_output(cls, history: List[Dict[str, str]], output_path: Path) -> int:
        target = cls.normalized_path(output_path)
        for index, record in enumerate(history):
            for path in cls.history_record_local_paths(record):
                if cls.normalized_path(path) == target:
                    return index
        return -1

    @classmethod
    def merge_history_record(cls, record: Dict[str, str], incoming: Dict[str, str]) -> bool:
        changed = False
        for key in ("title", "file", "album_id", "cover_url"):
            if not record.get(key) and incoming.get(key):
                record[key] = incoming.get(key, "")
                changed = True
        for key in ("path", "pdf_path", "image_dir"):
            incoming_value = incoming.get(key) or ""
            if incoming_value and (not record.get(key) or not cls.is_completed_local_resource(Path(record.get(key)).expanduser())):
                record[key] = incoming_value
                changed = True
        outputs = []
        for value in [record.get("path") or "", record.get("pdf_path") or "", record.get("image_dir") or ""]:
            if str(value).strip():
                outputs.append(str(value))
        for source in (record.get("outputs") or [], incoming.get("outputs") or []):
            if isinstance(source, list):
                outputs.extend(str(value) for value in source if str(value).strip())
        unique_outputs = []
        seen_outputs = set()
        for value in outputs:
            path = Path(value).expanduser()
            if not cls.is_completed_local_resource(path):
                continue
            key = cls.normalized_path(path)
            if key in seen_outputs:
                continue
            seen_outputs.add(key)
            unique_outputs.append(str(path))
        if unique_outputs != (record.get("outputs") or []):
            record["outputs"] = unique_outputs
            changed = True
        if incoming.get("image_dir") and record.get("format") not in {"images", "image"}:
            record["format"] = "images"
            changed = True
        return changed


class LocalReaderImportWorker(LocalHistorySyncWorker):
    imported = Signal(object, int, int)

    def __init__(self, history: List[Dict[str, str]], paths: List[str], album_cache: Dict[str, Dict], batch: bool = False, parent=None):
        super().__init__(history, [], album_cache, parent)
        self.paths = [str(path) for path in paths if str(path).strip()]
        self.batch = batch

    def run(self):
        try:
            history, added, selected_index = self.import_history()
            if not self.isInterruptionRequested():
                self.imported.emit(history, added, selected_index)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))

    def import_history(self) -> tuple[List[Dict[str, str]], int, int]:
        history = copy.deepcopy(self.history)
        added = 0
        selected_index = -1
        paths = self.import_candidate_paths()
        for path in paths:
            album_id = self.album_id_from_local_output(path)
            record = self.history_record_from_local_output(path, album_id, len(history), managed=False)
            if record is None:
                continue
            existing_index = self.find_history_index_for_album(history, album_id) if album_id else -1
            if existing_index < 0:
                existing_index = self.find_history_index_for_output(history, path)
            if existing_index >= 0:
                changed = self.merge_history_record(history[existing_index], record)
                history[existing_index]["managed"] = "0"
                selected_index = existing_index
                if changed:
                    added += 1
                continue
            history.append(record)
            selected_index = len(history) - 1
            added += 1
        return history, added, selected_index

    def import_candidate_paths(self) -> List[Path]:
        raw_paths = [Path(value).expanduser() for value in self.paths]
        if not self.batch:
            return raw_paths
        candidates: List[Path] = []
        seen = set()
        for root in raw_paths:
            outputs = self.iter_completed_local_outputs(root)
            if not outputs:
                outputs = [root]
            for path in outputs:
                key = self.normalized_path(path)
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(path)
        return candidates


class LocalReaderPrepareWorker(QThread):
    prepared = Signal(object)
    failed = Signal(str, object)

    def __init__(
        self,
        history_index: int,
        record: Dict[str, str],
        mode: str,
        output_dir: Path,
        default_output_dir: Path,
        parent=None,
    ):
        super().__init__(parent)
        self.history_index = history_index
        self.record = copy.deepcopy(record)
        self.mode = mode
        self.output_dir = Path(output_dir)
        self.default_output_dir = Path(default_output_dir)

    def run(self):
        try:
            result = prepare_local_history_reader_source(
                self.record,
                self.mode,
                self.output_dir,
                self.default_output_dir,
            )
            result["history_index"] = self.history_index
            result["record"] = self.record
            if not self.isInterruptionRequested():
                self.prepared.emit(result)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc), {"history_index": self.history_index, "record": self.record})


class HistoryLocalCoverWorker(QThread):
    resolved = Signal(str, str)
    failed = Signal(str, str)

    def __init__(self, cache_key: str, record: Dict[str, str], parent=None):
        super().__init__(parent)
        self.cache_key = cache_key
        self.record = copy.deepcopy(record)

    def run(self):
        try:
            path = find_history_local_cover_path(self.record)
            if not self.isInterruptionRequested():
                self.resolved.emit(self.cache_key, str(path or ""))
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(self.cache_key, str(exc))


class HistoryResourceDeleteWorker(QThread):
    completed = Signal(str, int, object)

    def __init__(self, title: str, paths: List[str], protected_paths: List[str], parent=None):
        super().__init__(parent)
        self.title = title
        self.paths = [str(path) for path in paths if str(path).strip()]
        self.protected_paths = [str(path) for path in protected_paths if str(path).strip()]

    def run(self):
        deleted = 0
        failed: List[tuple[str, str]] = []
        for path in self.sorted_delete_paths([Path(value).expanduser() for value in self.paths]):
            if self.isInterruptionRequested():
                break
            if self.is_protected_path(path):
                continue
            if not path.exists():
                continue
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                deleted += 1
            except Exception as exc:
                failed.append((str(path), str(exc)))
        if not self.isInterruptionRequested():
            self.completed.emit(self.title, deleted, failed)

    @staticmethod
    def sorted_delete_paths(paths: List[Path]) -> List[Path]:
        unique: Dict[str, Path] = {}
        for path in paths:
            try:
                normalized = str(path.resolve(strict=False)).lower()
            except Exception:
                normalized = str(path).lower()
            unique[normalized] = path
        return sorted(unique.values(), key=lambda item: len(item.parts), reverse=True)

    def is_protected_path(self, path: Path) -> bool:
        try:
            target = path.resolve(strict=False)
            protected = {Path(value).expanduser().resolve(strict=False) for value in self.protected_paths}
            return target in protected
        except Exception:
            return False
