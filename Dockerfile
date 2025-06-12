# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Install wget and other dependencies, then manually download and install wkhtmltoimage
# This is necessary because it's been removed from modern Debian repositories.
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    xvfb \
    libxrender1 \
    && wget https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb \
    && dpkg -i wkhtmltox_0.12.6-1.buster_amd64.deb \
    && apt-get -f install \
    && rm -f wkhtmltox_0.12.6-1.buster_amd64.deb \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code into the container
COPY . .

# Set the command to run your application using gunicorn
# The xvfb-run command creates a virtual screen for wkhtmltoimage to run against
CMD ["xvfb-run", "gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "weatherappbot:app"]