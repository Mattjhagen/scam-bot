FROM python:3.12-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN groupadd -r scambot && useradd -r -g scambot scambot && mkdir -p /home/scambot && chown scambot:scambot /home/scambot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM base AS runtime

COPY . .
RUN mkdir -p /app/data /app/src/data && chown -R scambot:scambot /app

USER scambot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, json; r=urllib.request.urlopen('http://localhost:8000/health', timeout=5); data=json.load(r); exit(0 if data.get('status')=='healthy' else 1)" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
