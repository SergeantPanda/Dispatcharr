# Base image with Python, Redis, PostgreSQL, FFmpeg, Nginx
FROM sergeantpanda/dispatcharr:base AS base

# --- Build frontend ---
FROM node:20 AS frontend-builder
WORKDIR /app
COPY . /app
RUN corepack enable && corepack prepare yarn@stable --activate && \
    cd frontend && yarn install && yarn build && \
    rm -rf frontend/node_modules frontend/.cache

# --- Final image based on the base ---
FROM sergeantpanda/dispatcharr:base AS final
ENV VIRTUAL_ENV=/dispatcharrpy
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
WORKDIR /app

# Copy application code
COPY . /app
# Copy built frontend assets
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Run Django collectstatic
RUN python manage.py collectstatic --noinput

CMD ["/app/docker/entrypoint.sh"]