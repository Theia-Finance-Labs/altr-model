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
RUN pip install poetry

# Copy only the Poetry configuration files needed for dependency installation
COPY pyproject.toml poetry.lock ./
COPY README.md ./

# Configure Poetry to avoid virtual environments and install dependencies
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

# Copy all project files
COPY src ./src
COPY conf ./conf

# Optionally copy data if needed for viz context
# COPY data ./data

# Expose Kedro Viz port
EXPOSE 4141

# Launch Kedro Viz
ENTRYPOINT ["kedro", "viz", "--host", "0.0.0.0", "--port", "4141", "--no-browser"]
