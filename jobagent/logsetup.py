"""Short local log lines. Profile values and message bodies are not written here."""

from __future__ import annotations

import logging
import re
from pathlib import Path


def configure(home: Path) -> logging.Logger:
    home.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("jobagent")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(home / "agent.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream)
    logger.propagate = False
    return logger


def safe_error(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"\S+@\S+", "[email]", text)
    return text[:180]
