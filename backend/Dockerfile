FROM python:3.11-slim

# Non-root runtime user
RUN useradd --create-home --uid 10001 splitshield

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV SPLITSHIELD_DATA_DIR=/data
RUN mkdir -p /data && chown splitshield:splitshield /data
VOLUME /data

USER splitshield
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
