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

# Install Poetry
RUN pip install poetry==1.8.3

# Copy all project files first
COPY src ./src
COPY conf ./conf
COPY pyproject.toml poetry.lock ./
COPY README.md ./

# Configure Poetry to avoid virtual environments and install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

# Optionally copy data if needed for viz context
# COPY data ./data

# Expose Kedro Viz port
EXPOSE 4141

# Run as non-root for security (port 4141 is unprivileged).
USER nobody

# Launch Kedro Viz in lite mode so startup does not import project pipeline
# modules (avoids heavy matplotlib/seaborn import chains and Cloud Run startup
# health-check timeouts).
ENTRYPOINT ["kedro", "viz", "run", "--host", "0.0.0.0", "--port", "4141", "--no-browser", "--lite"]
