# ES Rally Benchmark Image
# Multi-arch (amd64 + arm64) for Intel and Graviton
FROM python:3.11-slim

# Install system dependencies and build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    bc \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install ES Rally with build requirements
RUN pip install --no-cache-dir wheel setuptools && \
    pip install --no-cache-dir esrally

# Create Rally config directory and data directories
RUN mkdir -p /root/.rally /tmp/.rally/data /tmp/.rally/src

# Pre-configure Rally
COPY rally.ini /root/.rally/rally.ini

WORKDIR /tmp

# Default command shows Rally version
CMD ["esrally", "--version"]
