FROM node:22-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3

ARG PLAYWRIGHT_MCP_VERSION=0.0.78
ARG AIOBOTO3_VERSION=15.5.0
ARG DEBIAN_MIRROR=http://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG PIP_INDEX_URL

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/home/node \
    PATH=/opt/venv/bin:/opt/playwright-mcp/node_modules/.bin:$PATH \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_MCP_ARGS="" \
    PLAYWRIGHT_MCP_COMMAND=playwright-mcp \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --no-install-recommends -y \
        bash \
        ca-certificates \
        chromium \
        curl \
        fonts-liberation \
        fonts-noto-color-emoji \
        fonts-wqy-zenhei \
        git \
        jq \
        python3 \
        python3-pip \
        python3-venv \
        ripgrep \
        unzip \
        wget \
        zip \
    && python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip setuptools wheel \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/playwright-mcp
RUN npm install --no-audit --no-fund \
        --registry="${NPM_REGISTRY}" \
        "@playwright/mcp@${PLAYWRIGHT_MCP_VERSION}" \
    && npm cache clean --force \
    && chown -R node:node /opt/playwright-mcp

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install ".[service,storage,milvuslite]"
RUN pip install "aioboto3==${AIOBOTO3_VERSION}"

RUN test -x /usr/bin/chromium \
    && mkdir -p /opt/playwright-browser \
    && ln -s /usr/bin/chromium /opt/playwright-browser/chrome

ENV PLAYWRIGHT_MCP_ARGS="--headless --no-sandbox --executable-path /opt/playwright-browser/chrome"

COPY --chown=node:node examples/agent_service ./examples/agent_service
RUN mkdir -p \
        /app/examples/agent_service/workspaces \
    && chown -R node:node /app/examples/agent_service

# AgentScope executes workspace commands through /bin/sh. Use Bash at runtime
# so skill installers can use Bash-only syntax such as process substitution.
RUN ln -sfT /bin/bash /bin/sh

USER node
WORKDIR /app/examples/agent_service

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
