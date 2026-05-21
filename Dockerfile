# Stage 1: Build the React frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/ui

# Copy only frontend package files to leverage caching
COPY ui/package*.json ./

# Install Node dependencies specifically for the frontend
RUN npm install

# Copy frontend source files
COPY ui/ ./

# Build React production bundle (generates /app/ui/dist)
RUN npm run build

# Stage 2: Build the FastAPI backend
FROM python:3.11-slim AS backend
WORKDIR /app

# Install system dependencies (build tools, curl, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements and install
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY app/ ./app/
COPY providers.json ./
COPY scripts/ ./scripts/

# Copy the built React assets from Stage 1 into the Python backend's expected directory
COPY --from=frontend-builder /app/ui/dist ./ui/dist

# Expose port (FastAPI defaults to 8000, Render sets PORT dynamically)
EXPOSE 8000

# Start command: runs Uvicorn reading the dynamic PORT variable set by Render, defaulting to 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
