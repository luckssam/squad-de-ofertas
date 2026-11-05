# Squad de Ofertas — Dockerfile multi-stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Instalar dependências de build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Imagem final
FROM python:3.12-slim

WORKDIR /app

# Criar usuário não-root
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Copiar dependências do builder
COPY --from=builder /root/.local /home/appuser/.local

# Copiar código
COPY --chown=appuser:appuser . .

# Criar diretório para tokens OAuth
RUN mkdir -p data && chown appuser:appuser data

# Variáveis de ambiente
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Porta
EXPOSE 8765

# Healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8765/api/health', timeout=3)" || exit 1

# Usuário não-root
USER appuser

# Comando
CMD ["python", "app.py"]