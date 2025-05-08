FROM sergeantpanda/dispatcharr:base

COPY . /app
WORKDIR /app

# Install frontend
RUN corepack enable && corepack prepare yarn@stable --activate && \
    cd frontend && yarn install && yarn build && \
    rm -rf node_modules .cache

# Run collectstatic and other Django prep
RUN python manage.py collectstatic --noinput

CMD ["/app/docker/entrypoint.sh"]