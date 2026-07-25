FROM python:3.12-slim

# pdfplumber is listed here even though only trimitdown-pdf (installed below)
# imports it. This layer is cached across rebuilds, and pdfplumber drags Pillow
# and pypdfium2 -- multi-megabyte binary wheels. Warming them here keeps them out
# of the layer that is invalidated every time the package changes.
# Deliberately unpinned, unlike requirements.txt: the image tracks current
# pdfplumber, and the range in packages/trimitdown-pdf governs what is valid.
RUN pip install --no-cache-dir "markitdown[all]" pdfplumber fastapi uvicorn python-multipart pillow tiktoken

WORKDIR /app
COPY docker-server/app.py docker-server/generate_icons.py mac-build/icon_master_1024.png ./
COPY docker-server/static static
COPY core core

# Движок ставится из рабочего дерева намеренно: NAS собирает текущую ревизию,
# это наш стенд, а не пользовательский канал.
COPY packages/trimitdown-pdf packages/trimitdown-pdf
RUN pip install --no-cache-dir ./packages/trimitdown-pdf

# Приложение ставится ПАКЕТОМ, а не копированием src/: только так консольная
# команда попадает на PATH, и `docker exec trimitdown-web trimitdown convert ...`
# начинает работать. Это и есть терминальный доступ к серверу -- вместо
# клиентского --server в pip-пакете.
COPY pyproject.toml README.md LICENSE ./
COPY src src
RUN pip install --no-cache-dir --no-deps .

RUN python generate_icons.py
RUN mkdir -p /app/archive

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile", "/certs/key.pem", "--ssl-certfile", "/certs/cert.pem"]
