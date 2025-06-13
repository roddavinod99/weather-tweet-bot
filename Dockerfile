# Dockerfile

# 1. Use an official Python runtime as a parent image
FROM python:3.11-slim

# 2. Set the working directory in the container
WORKDIR /app

# 3. Install system dependencies required by wkhtmltoimage
#    'wkhtmltopdf' package includes 'wkhtmltoimage'
#    'xvfb' is a virtual framebuffer, often needed for headless rendering
RUN apt-get update && apt-get install -y \
    wkhtmltopdf \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# 4. Copy the requirements file and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of your application code into the container
COPY . .

# 6. Expose the port the app runs on
EXPOSE 8080

# 7. Define the command to run your app using Gunicorn
#    The PORT environment variable will be automatically set by Cloud Run.
CMD ["gunicorn", "--bind", "0.0.0.0:$PORT", "--workers", "1", "--threads", "8", "--timeout", "0", "app:app"]