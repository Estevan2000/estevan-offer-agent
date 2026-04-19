# Offer Agent backend — production image
# Build: docker build -t offer-agent .
# Run:   docker run -p 8000:8000 offer-agent

FROM python:3.11-slim

# System deps: qpdf (for PDF linearize/normalize step)
RUN apt-get update \
    && apt-get install -y --no-install-recommends qpdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so Docker caches them between code changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code + blank form + frontend
COPY . .

# Render sets $PORT; default to 8000 when not set
ENV PORT=8000
EXPOSE 8000

# Start the FastAPI server
CMD ["sh", "-c", "uvicorn backend_server:app --host 0.0.0.0 --port ${PORT}"]
