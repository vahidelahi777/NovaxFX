FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for layer-cache efficiency
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[prod]"

COPY scripts/ ./scripts/

# Mounted as volumes at runtime — created here so the image has the dirs
RUN mkdir -p data logs

CMD ["python", "scripts/prod_daemon_xauusd.py"]
