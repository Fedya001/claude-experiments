# Playwright image ships Chromium + its system deps (needed for Strava photos).
FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "playwright==1.49.1"
COPY bot ./bot
COPY apps ./apps
CMD ["python", "-m", "bot"]
