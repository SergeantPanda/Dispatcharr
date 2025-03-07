#!/bin/bash

# Inwitialize PostgreSQL database
if [ -z "$(ls -A "/data")" ]; then
    echo_with_timestamp "Initializing PostgreSQL database..."
    mkdir -p "/data"
    chown -R postgres:postgres "/data"
    chmod 700 "/data"

    # Initialize PostgreSQL
    su - postgres -c "/usr/lib/postgresql/14/bin/initdb -D /data"
    # Configure PostgreSQL
    echo "host all all 0.0.0.0/0 md5" >> "/data/pg_hba.conf"
    echo "listen_addresses='*'" >> "/data/postgresql.conf"

    # Start PostgreSQL
    echo "Starting Postgres..."
    su - postgres -c "/usr/lib/postgresql/14/bin/pg_ctl -D /data start -w -t 300 -o '-c port=${POSTGRES_PORT}'"
    # Wait for PostgreSQL to be ready
    until su - postgres -c "/usr/lib/postgresql/14/bin/pg_isready -h ${POSTGRES_HOST} -p ${POSTGRES_PORT}" >/dev/null 2>&1; do
        echo_with_timestamp "Waiting for PostgreSQL to be ready..."
        sleep 1
    done

    postgres_pid=$(su - postgres -c "/usr/lib/postgresql/14/bin/pg_ctl -D /data status" | sed -n 's/.*PID: \([0-9]\+\).*/\1/p')

    # Setup database if needed
    if ! su - postgres -c "psql -p ${POSTGRES_PORT} -tAc \"SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB';\"" | grep -q 1; then
        # Create PostgreSQL database
        echo_with_timestamp "Creating PostgreSQL database..."
        su - postgres -c "createdb -p ${POSTGRES_PORT} ${POSTGRES_DB}"

        # Create user, set ownership, and grant privileges
        echo_with_timestamp "Creating PostgreSQL user..."
        su - postgres -c "psql -p ${POSTGRES_PORT} -d ${POSTGRES_DB}" <<EOF
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '$POSTGRES_USER') THEN
        CREATE ROLE $POSTGRES_USER WITH LOGIN PASSWORD '$POSTGRES_PASSWORD';
    END IF;
END
\$\$;
EOF
        echo_with_timestamp "Setting PostgreSQL user privileges..."
        su postgres -c "/usr/lib/postgresql/14/bin/psql -p ${POSTGRES_PORT} -c \"ALTER DATABASE ${POSTGRES_DB} OWNER TO $POSTGRES_USER;\""
        su postgres -c "/usr/lib/postgresql/14/bin/psql -p ${POSTGRES_PORT} -c \"GRANT ALL PRIVILEGES ON DATABASE ${POSTGRES_DB} TO $POSTGRES_USER;\""
        # Finished setting up PosgresSQL database
        echo_with_timestamp "PostgreSQL database setup complete."
    fi

    kill $postgres_pid
    while kill -0 $postgres_pid; do
        sleep 1
    done
fi
