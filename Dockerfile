# Use a lightweight Python base image
FROM python:3.10-slim

# Set the working directory
WORKDIR /app

# Add the application directory to PYTHONPATH so that Kedro finds your project modules (if needed)
ENV PYTHONPATH="/app:$PYTHONPATH"

# Install Kedro and Kedro-viz
RUN pip install kedro kedro-viz

# Expose the port Kedro Viz will run on
EXPOSE 4141

# Start the Kedro Viz server with host binding to all interfaces, port 4141, and disable auto-opening the browser
ENTRYPOINT ["kedro", "viz", "--host", "0.0.0.0", "--port", "4141", "--no-browser"]
