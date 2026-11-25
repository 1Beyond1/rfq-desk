FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RFQ_BIND_HOST=0.0.0.0 \
    RFQ_DB=/app/var/rfq.sqlite3

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN groupadd --gid 10001 rfq \
    && useradd --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin rfq \
    && mkdir -p /app/var/uploads \
    && chown -R 10001:10001 /app/var

USER 10001:10001

EXPOSE 5311 8311

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8311/api/auth/session', timeout=3)" || exit 1

CMD ["python", "distribution/serve.py"]
