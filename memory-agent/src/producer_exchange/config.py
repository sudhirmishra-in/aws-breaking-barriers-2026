"""Runtime settings, read once from the environment at the composition root."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    model_id: str = "us.anthropic.claude-opus-5-5"
    aws_region: str = "us-west-2"
    max_output_tokens: int = 16000
    store_backend: Literal["sqlite", "dynamodb"] = "sqlite"
    sqlite_path: Path = PROJECT_ROOT / ".local" / "memory.db"
    dynamodb_table: str = "producer-exchange-memory"
    data_dir: Path = PROJECT_ROOT / "data" / "sample"
    working_memory_ttl_seconds: int = 7 * 24 * 60 * 60  # A fixed deadline from the exchange's first save.
    transcript_window_messages: int = 12
    max_stage_runs: int = 8
    max_model_calls_per_run: int = 4

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            model_id=os.getenv("PX_MODEL_ID", defaults.model_id),
            aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or defaults.aws_region,
            store_backend=os.getenv("PX_STORE", defaults.store_backend),  # type: ignore[arg-type]
            sqlite_path=Path(os.getenv("PX_SQLITE_PATH", defaults.sqlite_path)),
            dynamodb_table=os.getenv("PX_DYNAMODB_TABLE", defaults.dynamodb_table),
            data_dir=Path(os.getenv("PX_DATA_DIR", defaults.data_dir)),
        )
