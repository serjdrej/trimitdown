FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "markitdown[all]" fastapi uvicorn python-multipart pillow tiktoken

WORKDIR /app
COPY nas-server/app.py nas-server/generate_icons.py ./
COPY nas-server/static static
COPY core core

RUN python generate_icons.py
RUN mkdir -p /app/archive

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile", "/certs/key.pem", "--ssl-certfile", "/certs/cert.pem"]
