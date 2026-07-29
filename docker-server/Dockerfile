FROM python:3.12-slim

WORKDIR /app
# The image used to install a hand-written list here, deliberately unpinned, so
# that it tracked current pdfplumber. That decision is reversed: an image is an
# artifact a user runs, and two builds of one commit resolving different
# versions is the mechanism that shipped a broken desktop bundle. The lock is
# copied on its own so this layer -- which drags Pillow and pypdfium2,
# multi-megabyte binary wheels -- is invalidated only when the graph changes,
# not on every edit to the application.
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

COPY docker-server/app.py docker-server/generate_icons.py mac-build/icon_master_1024.png ./
COPY docker-server/static static
COPY core core

# Движок ставится из рабочего дерева намеренно: NAS собирает текущую ревизию,
# это наш стенд, а не пользовательский канал.
COPY packages/trimitdown-pdf packages/trimitdown-pdf
# Приложение ставится ПАКЕТОМ, а не копированием src/: только так консольная
# команда попадает на PATH, и `docker exec trimitdown-web trimitdown convert ...`
# начинает работать. Это и есть терминальный доступ к серверу -- вместо
# клиентского --server в pip-пакете. Не editable: editable кладёт .pth на
# /app/src, и образ начинает зависеть от того, что дерево осталось на месте.
COPY pyproject.toml README.md LICENSE ./
COPY src src
# --no-deps is load-bearing: resolving again here would bypass the lock.
RUN pip install --no-cache-dir --no-deps . ./packages/trimitdown-pdf

RUN python generate_icons.py
RUN mkdir -p /app/archive

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", \
     "--ssl-keyfile", "/certs/key.pem", "--ssl-certfile", "/certs/cert.pem"]
