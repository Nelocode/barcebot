# Usa Python 3.12 como base (ya incluye curl)
FROM python:3.12-slim

WORKDIR /app

# ── Instalar Node.js 20 ──
RUN apt-get update && apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

# ── Copiar dependencias primero (caché de Docker) ──
COPY requirements.txt package.json ./

# ── Instalar dependencias ──
RUN pip install --no-cache-dir -r requirements.txt && \
    npm install --production --ignore-scripts && \
    npm cache clean --force

# ── Copiar el código ──
COPY . .

# ── Puerto del panel ──
EXPOSE 5000

# ── Script de entrada: lanza los 3 procesos ──
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
