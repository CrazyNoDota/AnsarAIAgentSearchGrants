FROM python:3.12-slim

WORKDIR /app

# Install system deps for Playwright and lxml
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers (for dynamic scrapers)
RUN playwright install chromium --with-deps

COPY . .

EXPOSE 8000
