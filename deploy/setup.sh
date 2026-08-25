#!/bin/bash
# Script di setup per server Hetzner Ubuntu 24.04
# Esegui i blocchi uno alla volta — non tutto insieme

# ============================================================
# BLOCCO 1 — Aggiorna il sistema e installa Docker
# ============================================================

apt update && apt upgrade -y

# Installa Docker (metodo ufficiale)
curl -fsSL https://get.docker.com | sh

# Verifica che Docker funzioni
docker --version


# ============================================================
# BLOCCO 2 — Installa nginx e certbot
# ============================================================

apt install -y nginx certbot python3-certbot-nginx


# ============================================================
# BLOCCO 3 — Scarica il codice dal tuo repository GitHub
# ============================================================

cd /opt
git clone https://github.com/jaco42/ilsa-crm-backend.git crm
cd crm


# ============================================================
# BLOCCO 4 — Crea il file .env con le variabili di produzione
# ============================================================

# Copia il template e aprilo con nano per compilarlo
cp deploy/env.production.example .env
nano .env

# Compila:
#   DATABASE_URL  → lascia com'è (punta al container "db")
#   DB_PASSWORD   → scegli una password sicura (es. "Ilsa2025!Crm")
#   SECRET_KEY    → genera con: python3 -c "import secrets; print(secrets.token_hex(32))"
#   RESEND_API_KEY → copia da resend.com
#   ALLOWED_ORIGINS → URL del frontend React


# ============================================================
# BLOCCO 5 — Avvia il database e il backend con Docker
# ============================================================

cd /opt/crm

# Esporta DB_PASSWORD per docker-compose (legge dal .env)
export $(grep DB_PASSWORD .env | xargs)

docker compose up -d

# Aspetta 10 secondi che PostgreSQL si avvii
sleep 10

# Verifica che i container girino
docker compose ps

# Verifica che il backend risponda
curl http://localhost:8000/health


# ============================================================
# BLOCCO 6 — Configura nginx
# ============================================================

# Sostituisci TUODOMINIO.IT con il tuo dominio reale nel file
# prima di copiarlo
# Copia la configurazione nginx
cp deploy/nginx.conf /etc/nginx/sites-available/crm
ln -s /etc/nginx/sites-available/crm /etc/nginx/sites-enabled/crm

# Rimuovi la configurazione default di nginx
rm -f /etc/nginx/sites-enabled/default

# Verifica che la configurazione sia ok
nginx -t

# Riavvia nginx
systemctl restart nginx


# ============================================================
# BLOCCO 7 — Ottieni il certificato SSL (HTTPS)
# ============================================================

# Prima assicurati che il dominio punti già all'IP di questo server
# (aggiorna il DNS e aspetta qualche minuto)

certbot --nginx -d api.ilsacrmbackend.online

# Certbot chiederà la tua email e accetti i termini.
# Alla fine configura nginx automaticamente per HTTPS.

# Verifica che il rinnovo automatico funzioni
certbot renew --dry-run


# ============================================================
# BLOCCO 8 — Importa i dati da Railway (se hai dati esistenti)
# ============================================================

# Sul tuo Mac — esporta da Railway
# (prendi la DATABASE_URL da Railway dashboard)
# pg_dump "postgresql://postgres:XXX@monorail.proxy.rlwy.net:PORT/railway" -Fc -f backup.dump

# Copia il dump sul server Hetzner
# scp backup.dump root@IP_HETZNER:/opt/crm/

# Sul server — importa nel database Docker
# docker exec -i crm-db-1 pg_restore -U ilsa_user -d ilsa_crm /opt/crm/backup.dump


# ============================================================
# BLOCCO 9 — Aggiorna il frontend con il nuovo URL backend
# ============================================================

# Nel file .env.production del frontend (ilsa-crm):
# VITE_API_BASE=https://api.ilsacrmbackend.online

# Poi fai deploy del frontend (Netlify rileva automaticamente il push su GitHub)


# ============================================================
# COMANDI UTILI PER IL FUTURO
# ============================================================

# Vedere i log del backend
# docker compose logs -f backend

# Riavviare dopo un aggiornamento del codice
# cd /opt/crm && git pull && docker compose up -d --build

# Backup manuale del database
# docker exec crm-db-1 pg_dump -U ilsa_user ilsa_crm > backup_$(date +%Y%m%d).sql
