# Use a lightweight Python base image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Add the application directory to PYTHONPATH so that Kedro finds your project modules
ENV PYTHONPATH="/app/src:$PYTHONPATH"

# Install system dependencies (for potential deps in Kedro plugins)
RUN apt-get update && apt-get install -y \
    build-essential \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy all project files first
COPY src ./src
COPY conf ./conf
COPY pyproject.toml uv.lock ./
COPY README.md ./

# Install dependencies into the system environment
ENV UV_PROJECT_ENVIRONMENT="/usr/local"
RUN uv sync --frozen --no-dev

# Optionally copy data if needed for viz context
# COPY data ./data

# Expose Kedro Viz port
EXPOSE 4141

# Launch Kedro Viz
ENTRYPOINT ["kedro", "viz", "--host", "0.0.0.0", "--port", "4141", "--no-browser"]
