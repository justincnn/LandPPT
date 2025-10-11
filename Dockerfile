# LandPPT Docker Image
# Multi-stage build for minimal image size

# Build stage
FROM python:3.11-slim AS builder

# Set environment variables for build
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for faster dependency management
RUN pip install --no-cache-dir uv

# Set work directory and copy dependency files
WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY src/ ./src/

# Install Python dependencies using uv
# uv sync will create venv at UV_PROJECT_ENVIRONMENT and install all dependencies
RUN uv sync && \
    uv pip install apryse-sdk>=11.5.0 --extra-index-url=https://pypi.apryse.com && \
    # Verify key packages are installed
    /opt/venv/bin/python -c "import uvicorn; import playwright; import fastapi" && \
    # Clean up build artifacts
    find /opt/venv -name "*.pyc" -delete && \
    find /opt/venv -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Production stage
FROM python:3.11-slim AS production

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src:/opt/venv/lib/python3.11/site-packages \
    PATH=/opt/venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright \
    HOME=/root \
    VIRTUAL_ENV=/opt/venv

# Install essential runtime dependencies and wkhtmltopdf
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    poppler-utils \
    libmagic1 \
    ca-certificates \
    curl \
    wget \
    chromium \
    libgomp1 \
    fonts-liberation \
    fonts-noto-cjk \
    fontconfig \
    netcat-openbsd \
    xfonts-75dpi \
    xfonts-base \
    libjpeg62-turbo \
    libxrender1 \
    libfontconfig1 \
    libx11-6 \
    libxext6 \
    && \
    # Download and install wkhtmltopdf from official releases
    WKHTMLTOPDF_VERSION="0.12.6.1-3" && \
    wget -q "https://github.com/wkhtmltopdf/packaging/releases/download/${WKHTMLTOPDF_VERSION}/wkhtmltox_${WKHTMLTOPDF_VERSION}.bookworm_amd64.deb" -O /tmp/wkhtmltox.deb && \
    dpkg -i /tmp/wkhtmltox.deb || apt-get install -f -y && \
    rm /tmp/wkhtmltox.deb && \
    fc-cache -fv && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache

# Create non-root user (for compatibility, but run as root)
RUN groupadd -r landppt && \
    useradd -r -g landppt -m -d /home/landppt landppt && \
    mkdir -p /home/landppt/.cache/ms-playwright /root/.cache/ms-playwright

# Copy Python packages from builder
COPY --from=builder /opt/venv /opt/venv

# Install Playwright browsers (chromium) - package already installed in builder stage
RUN python -m playwright install chromium && \
    chown -R landppt:landppt /home/landppt && \
    rm -rf /tmp/* /var/tmp/*

# Set work directory
WORKDIR /app

# Copy application code (minimize layers)
COPY run.py ./
COPY src/ ./src/
COPY template_examples/ ./template_examples/
COPY docker-healthcheck.sh docker-entrypoint.sh ./
COPY .env.example ./.env

# Create directories and set permissions in one layer
RUN chmod +x docker-healthcheck.sh docker-entrypoint.sh && \
    mkdir -p temp/ai_responses_cache temp/style_genes_cache temp/summeryanyfile_cache temp/templates_cache \
             research_reports lib/Linux lib/MacOS lib/Windows uploads data && \
    chown -R landppt:landppt /app /home/landppt && \
    chmod -R 755 /app /home/landppt && \
    chmod 666 /app/.env

# Keep landppt user but run as root to handle file permissions
# USER landppt

# Expose port
EXPOSE 8000

# Minimal health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=2 \
    CMD ./docker-healthcheck.sh

# Set entrypoint and command
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "run.py"]