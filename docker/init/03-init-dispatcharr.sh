#!/bin/bash

# Required so both uwsgi and nginx (www-data) can use it
# @TODO: change nginx to run as the same use as uwsgi
touch /app/uwsgi.sock
chown -R $PUID:$PGID /app
chown $PUID:www-data /app/uwsgi.sock
chmod 777 /app/uwsgi.sock
