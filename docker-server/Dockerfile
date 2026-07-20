FROM python:3.12-slim

RUN pip install --no-cache-dir "markitdown[all]" pdfplumber fastapi uvicorn python-multipart pillow tiktoken

WORKDIR /app
COPY docker-server/app.py docker-server/generate_icons.py mac-build/icon_master_1024.png ./
COPY docker-server/static static
COPY core core

# core/converter.py imports trimitdown_pdf, which no longer lives under core/.
# Without this the image builds fine and then fails at the first PDF upload.
COPY packages/trimitdown-pdf packages/trimitdown-pdf
RUN pip install --no-cache-dir ./packages/trimitdown-pdf

RUN python generate_icons.py
RUN mkdir -p /app/archive

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile", "/certs/key.pem", "--ssl-certfile", "/certs/cert.pem"]
