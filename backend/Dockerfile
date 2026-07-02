FROM python:3.12-slim

WORKDIR /app

# System deps: gcc for asyncpg, pango/cairo for WeasyPrint PDF rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libcairo2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Run alembic migrations before starting uvicorn.
# Prevents "column does not exist" crashes when new migrations
# are added but not manually applied to prod.
CMD alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000
