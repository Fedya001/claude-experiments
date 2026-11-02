FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY requirements.txt .
# --only-shell: the bot only runs Chromium headless, so skip the full browser (~390 MB).
# One layer, with apt lists and caches removed, so nothing deleted later still takes space.
RUN pip install -r requirements.txt \
 && playwright install --with-deps --only-shell chromium \
 && rm -rf /var/lib/apt/lists/* /root/.cache /tmp/*

COPY bot ./bot
COPY apps ./apps
CMD ["python", "-m", "bot"]
