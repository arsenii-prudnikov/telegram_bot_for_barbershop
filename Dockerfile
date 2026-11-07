FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY termin_bot ./termin_bot
COPY salon.example.yaml .

ENV DATABASE=/data/termine.db WEB_HOST=0.0.0.0 WEB_PORT=8080 PYTHONUNBUFFERED=1 TZ=Europe/Berlin
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"
CMD ["python", "-m", "termin_bot", "run"]
