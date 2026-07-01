#!/bin/bash
# ===========================================================================
# Superset + PostgreSQL bootstrap (Amazon Linux 2023)
# NOTE: this file is rendered by Terraform's templatefile(). A single-brace
# dollar-name is substituted by Terraform; a double-dollar escapes it so the
# brace form survives into the written file (used by docker compose / the
# containers); a plain $VAR with no braces is an ordinary runtime shell var.
# ===========================================================================
set -euxo pipefail

# --- 1. Swap: t3.micro has ~1 GiB RAM; Superset+Postgres need headroom ------
if [ ! -f /swapfile ]; then
  dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# --- 2. Docker + compose plugin --------------------------------------------
dnf update -y
dnf install -y docker
systemctl enable --now docker
mkdir -p /usr/local/lib/docker/cli-plugins
curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# --- 3. App directory + config files ---------------------------------------
mkdir -p /opt/hnx
cd /opt/hnx

# .env (values injected by Terraform; docker compose auto-loads this file)
cat > /opt/hnx/.env <<'ENVEOF'
DB_USER=${db_user}
DB_PASSWORD=${db_password}
SUPERSET_DB_NAME=${superset_db_name}
METRICS_DB_NAME=${metrics_db_name}
SUPERSET_SECRET_KEY=${superset_secret_key}
SUPERSET_ADMIN_USER=${superset_admin_user}
SUPERSET_ADMIN_PASSWORD=${superset_admin_password}
SUPERSET_IMAGE=${superset_image}
ENVEOF
chmod 600 /opt/hnx/.env

# Postgres init: create the analytics DB next to the superset metadata DB.
# initdb.d scripts run only once, on an empty data volume.
cat > /opt/hnx/init-metrics-db.sh <<'INITEOF'
#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE $${METRICS_DB_NAME};
EOSQL
INITEOF
chmod +x /opt/hnx/init-metrics-db.sh

# superset_config.py: mandatory SECRET_KEY + metadata DB URI, both from env
cat > /opt/hnx/superset_config.py <<'CONFEOF'
import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = os.environ["SQLALCHEMY_DATABASE_URI"]

# Keep it light on t3.micro
SUPERSET_WEBSERVER_TIMEOUT = 120
ROW_LIMIT = 50000
CONFEOF

# docker-compose.yml: postgres (2 DBs) + superset (-dev image = has psycopg2)
cat > /opt/hnx/docker-compose.yml <<'COMPOSEEOF'
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_USER: $${DB_USER}
      POSTGRES_PASSWORD: $${DB_PASSWORD}
      POSTGRES_DB: $${SUPERSET_DB_NAME}
      METRICS_DB_NAME: $${METRICS_DB_NAME}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init-metrics-db.sh:/docker-entrypoint-initdb.d/init-metrics-db.sh
    ports:
      - "5432:5432"          # published to host so the loader Lambda reaches EC2:5432
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${DB_USER}"]
      interval: 10s
      timeout: 5s
      retries: 12

  superset:
    image: $${SUPERSET_IMAGE}
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    environment:
      SUPERSET_SECRET_KEY: $${SUPERSET_SECRET_KEY}
      SUPERSET_CONFIG_PATH: /app/superset_config.py
      SQLALCHEMY_DATABASE_URI: postgresql+psycopg2://$${DB_USER}:$${DB_PASSWORD}@postgres:5432/$${SUPERSET_DB_NAME}
    volumes:
      - ./superset_config.py:/app/superset_config.py
    ports:
      - "8088:8088"
    command: >
      gunicorn --bind 0.0.0.0:8088 --workers 2 --worker-class gthread
      --threads 4 --timeout 120 "superset.app:create_app()"

volumes:
  pgdata:
COMPOSEEOF

# --- 4. Boot the stack -----------------------------------------------------
set -a
source /opt/hnx/.env
set +a

docker compose pull
docker compose up -d postgres

# wait for postgres to accept connections
for i in $(seq 1 30); do
  if docker compose exec -T postgres pg_isready -U "$DB_USER" >/dev/null 2>&1; then
    break
  fi
  sleep 5
done

# initialise Superset metadata DB + admin user (idempotent; safe to re-run)
docker compose run --rm superset superset db upgrade
docker compose run --rm superset superset fab create-admin \
  --username "$SUPERSET_ADMIN_USER" --firstname Admin --lastname User \
  --email admin@hnx.local --password "$SUPERSET_ADMIN_PASSWORD" || true
docker compose run --rm superset superset init

docker compose up -d superset
