# NEPENTHE | Urban-Future-Weather Engine
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UFWE_DATA_DIR=/data \
    UFWE_LOCAL_DATA_DIR=/localdata \
    UFWE_CACHE_DIR=/cache \
    UFWE_DOWNLOAD_DIR=/downloads \
    UFWE_PORT=8610

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY static/ static/

# Non-root runtime user; /localdata holds the synced corpus,
# /cache the warming JSON, /downloads the built zip artifacts
RUN useradd --create-home --uid 1000 sofuser \
    && mkdir -p /localdata /cache /downloads \
    && chown -R sofuser:sofuser /localdata /cache /downloads
USER sofuser

EXPOSE 8610
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8610/healthz', timeout=4).status==200 else 1)"

CMD ["python", "-m", "app.main"]
