# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13.12

FROM python:${PYTHON_VERSION}-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system invoice-triage \
    && useradd --system --gid invoice-triage --create-home invoice-triage

COPY pyproject.toml README.md ./
COPY src/ ./src/

FROM base AS runtime

RUN python -m pip install .

COPY alembic.ini ./
COPY fixtures/ ./fixtures/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/

USER invoice-triage

# The AgentCore entrypoint will be added when the agent runtime is implemented.
# This target currently provides the reusable application execution environment.

FROM base AS test

ENV PYTEST_ADDOPTS="-p no:cacheprovider"

RUN python -m pip install ".[dev]"

COPY alembic.ini ./
COPY fixtures/ ./fixtures/
COPY migrations/ ./migrations/
COPY tests/ ./tests/

USER invoice-triage

CMD ["python", "-m", "pytest"]
