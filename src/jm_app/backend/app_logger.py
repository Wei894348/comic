from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from .runtime_paths import log_dir


class AppLog:
    logger = logging.getLogger("comic18")
    stream_handler: Optional[logging.Handler] = None
    file_handler: Optional[logging.Handler] = None
    log_file: Optional[Path] = None

    @classmethod
    def init(cls, level: int = logging.INFO) -> Path:
        cls.logger.setLevel(logging.DEBUG)
        cls.logger.propagate = False
        formatter = logging.Formatter("%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s")

        if cls.stream_handler is None:
            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            stream_handler.setLevel(level)
            cls.logger.addHandler(stream_handler)
            cls.stream_handler = stream_handler
        else:
            cls.stream_handler.setLevel(level)

        day = time.strftime("%Y%m%d", time.localtime())
        log_file = log_dir() / f"{day}.log"
        if cls.file_handler is None or cls.log_file != log_file:
            if cls.file_handler is not None:
                cls.logger.removeHandler(cls.file_handler)
                cls.file_handler.close()
            file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(level)
            cls.logger.addHandler(file_handler)
            cls.file_handler = file_handler
            cls.log_file = log_file
        else:
            cls.file_handler.setLevel(level)
        return log_file

    @classmethod
    def set_level(cls, level: int) -> None:
        cls.init(level)

    @classmethod
    def debug(cls, message: str, *args, **kwargs) -> None:
        cls.init()
        kwargs.setdefault("stacklevel", 2)
        cls.logger.debug(message, *args, **kwargs)

    @classmethod
    def info(cls, message: str, *args, **kwargs) -> None:
        cls.init()
        kwargs.setdefault("stacklevel", 2)
        cls.logger.info(message, *args, **kwargs)

    @classmethod
    def warning(cls, message: str, *args, **kwargs) -> None:
        cls.init()
        kwargs.setdefault("stacklevel", 2)
        cls.logger.warning(message, *args, **kwargs)

    @classmethod
    def error(cls, message: str, *args, **kwargs) -> None:
        cls.init()
        kwargs.setdefault("stacklevel", 2)
        cls.logger.error(message, *args, **kwargs)

    @classmethod
    def exception(cls, message: str, *args, **kwargs) -> None:
        cls.init()
        kwargs.setdefault("stacklevel", 2)
        cls.logger.exception(message, *args, **kwargs)
