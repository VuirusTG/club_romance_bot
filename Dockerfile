# ==========================================
# Dockerfile for Club Romance Telegram Bot
# Compatible with Docker Compose & Hugging Face Spaces
# ==========================================
FROM python:3.12-slim

# Prevent Python from writing .pyc files and enable unbuffered output for real-time logging
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=7860

# Install runtime tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user (UID 1000 for HF Spaces compatibility)
RUN groupadd -g 1000 botuser && \
    useradd -u 1000 -g botuser -m -s /bin/bash botuser

WORKDIR /app

# Install Python dependencies first for caching layers
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot application source code & data
COPY bot/ /app/bot/
COPY scripts/ /app/scripts/
COPY club_romance.db /app/club_romance.db

# Create directories for persistent storage and logs with full permissions
RUN mkdir -p /app/logs /app/data && \
    chown -R botuser:botuser /app && \
    chmod 664 /app/club_romance.db

# Expose default HTTP port for Hugging Face Spaces health check
EXPOSE 7860

# Switch to non-root user
USER botuser

# Health check verifies web server is responding
HEALTHCHECK --interval=60s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:7860/health || exit 1

# Default command to run the Telegram bot
CMD ["python", "-m", "bot.main"]
