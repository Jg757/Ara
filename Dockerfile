FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bridge.py .
COPY memory.py .
COPY vector_memory.py .
COPY google_services.py .
COPY knowledge_base.py .
COPY persona.txt .

# Cloud Run uses PORT environment variable
ENV PORT=8080

# Run the bridge
CMD ["python", "bridge.py"]
