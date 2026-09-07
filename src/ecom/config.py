from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    source_dsn: str
    warehouse_dsn: str
    data_dir: Path
    bootstrap_loaded_at: str
    page_size: int

    @staticmethod
    def from_env() -> Settings:
        return Settings(
            source_dsn=_env(
                "SOURCE_READER_DSN",
                _env("SOURCE_DSN", "postgresql://source_app:source_pw@localhost:5433/ecom_source"),
            ),
            warehouse_dsn=_env(
                "WAREHOUSE_DSN",
                "postgresql://warehouse_app:warehouse_pw@localhost:5434/ecom_warehouse",
            ),
            data_dir=Path(_env("DATA_DIR", "./data")),
            bootstrap_loaded_at=_env("BOOTSTRAP_LOADED_AT", "2018-10-20T00:00:00+00:00"),
            page_size=int(_env("BATCH_PAGE_SIZE", "5000")),
        )
