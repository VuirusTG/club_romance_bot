import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(level: str = "INFO") -> None:
    Path("logs").mkdir(exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level.upper())

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    errors = RotatingFileHandler("logs/errors.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    errors.setLevel(logging.ERROR)
    errors.setFormatter(formatter)
    root.addHandler(errors)

