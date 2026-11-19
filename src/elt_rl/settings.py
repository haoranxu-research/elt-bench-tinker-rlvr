"""Read only the project settings used by the CLI, without shell evaluation."""

import os
import re
from pathlib import Path

OFFICIAL_NAMES = (
    "ELT_BENCH_ROOT", "ELT_BOOKS_INPUT_DIR", "ELT_GT_SNOWFLAKE",
    "ELT_SNOWFLAKE_CREDENTIAL_JSON", "ELT_AIRBYTE_URL",
)
NAMES = (*OFFICIAL_NAMES, "ELT_TERRAFORM", "TINKER_API_KEY", "TINKER_PROJECT_ID", "TINKER_MODEL")
DEFAULT_MODEL = "Qwen/Qwen3.5-4B"
DEFAULT_RENDERER = "qwen3_5_disable_thinking"


class ConfigurationError(ValueError):
    """A message written by this project and safe to show to the operator."""


def read_settings(file: Path) -> dict[str, str]:
    values = {}
    if file.is_file():
        try:
            raw = file.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError):
            raise ConfigurationError("could not read the local environment file") from None
        for line in raw.splitlines():
            key, separator, value = line.strip().partition("=")
            if separator and key.strip() in NAMES:
                values[key.strip()] = value.strip()
    return {key: os.environ.get(key) or values.get(key, "") for key in NAMES}


def check_model_id(model: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*(?::[A-Za-z0-9_.-]+)*", model):
        raise ConfigurationError("model must be a published Tinker model ID")
