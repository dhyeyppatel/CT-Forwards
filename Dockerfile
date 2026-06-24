FROM python:3.11-slim

# Metadata
LABEL maintainer="MN Bots" \
      description="MN Auto Forward Bot — Userbot & Bot mode"

# Set working directory
WORKDIR /app

# Install dependencies first (layer-cached)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Default command
CMD ["python", "main.py"]
