# Usa una base image slim per ridurre le dimensioni
FROM --platform=linux/arm/v7 python:3.12-alpine

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
    # Scarica e installa Docker CLI
    && curl -sSL https://download.docker.com/linux/static/stable/armhf/docker-20.10.9.tgz \
    | tar xzvf - --strip 1 -C /usr/local/bin docker/docker && \
    rm -rf /var/cache/apk/*

# Installa le dipendenze Python
RUN pip install --no-cache-dir flask docker aiohttp gunicorn

# Copia il contenuto della directory corrente nel container in /app
COPY . /app

EXPOSE 5000

ARG VERSION

ENV VERSION=${VERSION}

# Imposta l'entrypoint
CMD ["gunicorn", "main:app", "-b", "0.0.0.0:5000", "--access-logfile=-", "--error-logfile=-"]
