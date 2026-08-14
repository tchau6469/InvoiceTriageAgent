# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13.12
ARG APP_UID=10001
ARG APP_GID=10001

FROM python:${PYTHON_VERSION}-slim-bookworm AS base

ARG APP_UID
ARG APP_GID

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid "${APP_GID}" invoice-triage \
    && useradd --uid "${APP_UID}" --gid invoice-triage --create-home \
        --shell /usr/sbin/nologin invoice-triage

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

FROM base AS ingestion

# Install the CPU wheel first so sentence-transformers does not resolve the
# much larger CUDA-enabled Linux distribution from the default package index.
RUN python -m pip install torch --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install ".[embeddings]"

COPY alembic.ini ./
COPY fixtures/ ./fixtures/
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/

USER invoice-triage

FROM base AS test

ENV PYTEST_ADDOPTS="-p no:cacheprovider"

RUN python -m pip install ".[dev]"

COPY alembic.ini ./
COPY fixtures/ ./fixtures/
COPY migrations/ ./migrations/
COPY tests/ ./tests/

USER invoice-triage

CMD ["python", "-m", "pytest"]
