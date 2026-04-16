# ── Slim Python-based container for tunnel-ssh server ────────────────────────
FROM python:3.12-slim

# Install only the extra utilities we need (Python/pip/venv already included)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        jq \
        tree \
        net-tools \
    && rm -rf /var/lib/apt/lists/*


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

