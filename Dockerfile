# ##################################################################
# ## STAGE 1: The "Builder" - Prepares wkhtmltoimage              ##
# ##################################################################
# Use a standard Debian image that can download and extract packages
FROM debian:buster-slim as builder

# Set an argument for the version to use
ARG WKHTMLTOX_VERSION=0.12.6-1

# Install tools needed to download and extract
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Download the official package and extract it
RUN wget https://github.com/wkhtmltopdf/packaging/releases/download/${WKHTMLTOX_VERSION}/wkhtmltox_${WKHTMLTOX_VERSION}.buster_amd64.deb \
    && dpkg-deb -x wkhtmltox_${WKHTMLTOX_VERSION}.buster_amd64.deb /


# ##################################################################
# ## STAGE 2: The "Final" Image - Our Python App                  ##
# ##################################################################
# Start from our desired slim Python image
FROM python:3.9-slim

# Set the working directory
WORKDIR /app

# Install only the necessary RUNTIME dependencies for wkhtmltoimage and our app
# This list is smaller and more reliable
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    libxrender1 \
    libfontconfig1 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Copy the compiled binaries from the "builder" stage into our final image
COPY --from=builder /usr/local/bin/wkhtmltoimage /usr/local/bin/wkhtmltoimage
COPY --from=builder /usr/local/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf

# Copy our application's requirements file
COPY requirements.txt .

# Install Python packages
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of our application code
COPY . .

# Set the final command to run the application
CMD ["xvfb-run", "gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "weatherappbot:app"]