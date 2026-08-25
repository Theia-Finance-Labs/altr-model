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

# Copy the project files needed to run the Streamlit batch-runner app
# (data/ and workspace/ are deliberately not copied - see below)
COPY src ./src
COPY conf ./conf
COPY notebooks ./notebooks
COPY pyproject.toml uv.lock ./
COPY README.md ./

# Install dependencies into the system environment, including the
# streamlit-only dependency group
ENV UV_PROJECT_ENVIRONMENT="/usr/local"
RUN uv sync --frozen --no-dev --group streamlit

# Don't run streamlit's first-launch prompt / usage-stats collection
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS="false"

# data/ is not baked into the image: run via docker-compose.yml, which
# mounts the local data/ and workspace/ folders at runtime so the app reads
# and writes whatever is on disk (docker compose up, then open
# http://localhost:8501 in your browser).

# Expose the Streamlit port
EXPOSE 8501

# Launch the Streamlit app
ENTRYPOINT ["streamlit", "run", "notebooks/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
