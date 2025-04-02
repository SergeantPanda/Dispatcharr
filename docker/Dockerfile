FROM python:3.13-slim AS builder

# Define build arguments with default values
ARG BRANCH=main
# This will be overridden by the GitHub Actions workflow
# when building the Docker image for production.
ARG REPO_URL=https://github.com/Dispatcharr/Dispatcharr

ENV PATH="/dispatcharrpy/bin:$PATH" \
    VIRTUAL_ENV=/dispatcharrpy \
    DJANGO_SETTINGS_MODULE=dispatcharr.settings \
    PYTHONUNBUFFERED=1 \
    DISPATCHARR_BUILD=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    gcc \
    git \
    libpcre3 \
    libpcre3-dev \
    python3-dev \
    wget && \
    echo "=== setting up nodejs ===" && \
    curl -sL https://deb.nodesource.com/setup_23.x -o /tmp/nodesource_setup.sh && \
    bash /tmp/nodesource_setup.sh && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    nodejs && \
    python -m pip install virtualenv && \
    virtualenv /dispatcharrpy && \
    git clone -b ${BRANCH} ${REPO_URL} /app && \
    cd /app && \
    rm -rf .git && \
    cd /app && \
    pip install --no-cache-dir -r requirements.txt && \
    python manage.py collectstatic --noinput && \
    cd /app/frontend && \
    npm install --legacy-peer-deps && \
    npm run build && \
    find . -maxdepth 1 ! -name '.' ! -name 'dist' -exec rm -rf '{}' \;

FROM python:3.13-slim

ENV PATH="/dispatcharrpy/bin:$PATH" \
    VIRTUAL_ENV=/dispatcharrpy \
    DJANGO_SETTINGS_MODULE=dispatcharr.settings \
    PYTHONUNBUFFERED=1

# Copy the virtual environment and application from the builder stage
COPY --from=builder /dispatcharrpy /dispatcharrpy
COPY --from=builder /app /app

# Install base dependencies with memory optimization
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libpcre3 \
    libpq-dev \
    nginx \
    procps \
    streamlink \
    wget \
    gnupg2 \
    gettext-base \
    lsb-release && \
    cp /app/docker/nginx.conf /etc/nginx/sites-enabled/default && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set up Redis repository in a separate step
RUN curl -fsSL https://packages.redis.io/gpg | gpg --dearmor -o /usr/share/keyrings/redis-archive-keyring.gpg && \
    chmod 644 /usr/share/keyrings/redis-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/redis-archive-keyring.gpg] https://packages.redis.io/deb $(lsb_release -cs) main" | tee /etc/apt/sources.list.d/redis.list && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y redis-server && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set up PostgreSQL repository and install in a separate step
RUN echo "=== setting up postgres ====" && \
    sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' && \
    wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/postgresql-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y postgresql-14 postgresql-contrib-14 && \
    mkdir -p /data && \
    apt-get remove -y gnupg2 lsb-release && \
    apt-get clean && \
    apt-get autoremove -y && \
    rm -rf /tmp/* /var/lib/apt/lists/* /var/tmp/*

WORKDIR /app

CMD ["/app/docker/entrypoint.sh"]
