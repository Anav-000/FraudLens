# Use official lightweight Python 3.12 image matching development environment
FROM python:3.12-slim

# Prevent Python from writing bytecode and enable unbuffered standard I/O for real-time logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies:
# - tesseract-ocr: core OCR engine
# - tesseract-ocr-eng: English OCR language pack
# - tesseract-ocr-hin: Hindi OCR language pack (FraudLens supported languages: eng, hin)
# - ca-certificates: required for secure outbound HTTPS calls to Google Gemini / Safe Browsing
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first for caching
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source code
COPY backend/app/ ./app/

# Expose default port (Render will dynamically inject $PORT)
EXPOSE 8000

# Start Uvicorn listening on 0.0.0.0:$PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
