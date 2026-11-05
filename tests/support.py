"""Helpers compartidos por pruebas que dependen de la configuración del entorno."""

import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """Resuelve DATA_DIR igual que el runtime, con rutas relativas al repositorio."""
    configured = Path(os.environ.get("DATA_DIR", "./data"))
    return configured if configured.is_absolute() else REPO / configured
