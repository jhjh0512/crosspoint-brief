FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Seoul

WORKDIR /app
# Dependencies first so source edits don't re-download them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH=/opt/venv/bin:$PATH \
    BRIEF_CONFIG=/config/config.toml \
    BRIEF_DATA_DIR=/data

# The compose file picks the runtime uid (default 1000) so /data stays writable on the NAS.
VOLUME ["/data"]
CMD ["brief", "run"]
