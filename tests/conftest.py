"""Guardas comunes para impedir que la suite opere sobre un entorno accidental."""

import os

import pytest


@pytest.fixture(autouse=True)
def _require_explicit_test_environment(request: pytest.FixtureRequest) -> None:
    """Exige una confirmación explícita antes de ejecutar pruebas con efectos externos."""
    if request.node.get_closest_marker("integration") and os.environ.get("ECOM_TEST_ENV") != "1":
        pytest.fail(
            "integration tests require ECOM_TEST_ENV=1 and an isolated Postgres/data environment"
        )
