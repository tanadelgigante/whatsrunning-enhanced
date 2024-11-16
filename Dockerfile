# Usa buildx per il multi-arch build
FROM python:3.12-alpine

# Imposta la directory di lavoro all'interno del container
WORKDIR /app

# Imposta le variabili d'ambiente
ENV LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1

# Installa le dipendenze di sistema e Docker CLI
RUN apk update && \
    apk add --no-cache \
    ca-certificates \
    curl \
    gnupg \
    # Determina l'architettura del sistema
    && ARCH=$(case $(uname -m) in \
        x86_64) echo "x86_64" ;; \
        aarch64) echo "aarch64" ;; \
        armv7l) echo "armhf" ;; \
        *) echo "unsupported" ;; \
    esac) \
    # Scarica la versione appropriata di Docker CLI basata sull'architettura
    && if [ "$ARCH" != "unsupported" ]; then \
        curl -sSL https://download.docker.com/linux/static/stable/$ARCH/docker-20.10.9.tgz \
        | tar xzvf - --strip 1 -C /usr/local/bin docker/docker; \
    fi \
    && rm -rf /var/cache/apk/*

# Installa le dipendenze Python
RUN pip install --no-cache-dir flask docker aiohttp gunicorn

# Copia il contenuto della directory corrente nel container in /app
COPY . /app

EXPOSE 5000

ARG VERSION

ENV VERSION=${VERSION}

# Imposta l'entrypoint
CMD ["gunicorn", "main:app", "-b", "0.0.0.0:5000", "--access-logfile=-", "--error-logfile=-"]