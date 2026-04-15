# ── Ubuntu-based container for tunnel-ssh server ─────────────────────────────
FROM ubuntu:24.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Install Python, pip, bash, and common utilities for testing
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-venv \
        bash \
        curl \
        jq \
        tree \
        net-tools \
    && rm -rf /var/lib/apt/lists/*

# Create a virtual environment so pip install works without --break-system-packages
RUN python3 -m venv /opt/tunnel-ssh-venv
ENV PATH="/opt/tunnel-ssh-venv/bin:$PATH"

# Copy the project into the container
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/

# Install the package (editable so we don't need a build step)
RUN pip install --no-cache-dir -e ".[dev]"

# Default shell for command execution
ENV TUNNEL_SSH_SHELL=/bin/bash

# Expose the default tunnel-ssh port
EXPOSE 222

# Start the server (token and port configurable via env / compose)
CMD ["tunnel-server", "--host", "0.0.0.0", "--port", "222"]

