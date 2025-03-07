#!/bin/bash

# Required so both uwsgi and nginx (www-data) can use it
# @TODO: change nginx to run as the same use as uwsgi

# NOTE: mac doesn't run as root, so only manage permissions
# if this script is running as root
if [ "$(id -u)" = "0" ]; then
    touch /app/uwsgi.sock
    chown -R $PUID:$PGID /app
    chown $PUID:www-data /app/uwsgi.sock
    chmod 777 /app/uwsgi.sock
fi
