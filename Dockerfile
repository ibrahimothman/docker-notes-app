# ---- Stage 1: builder ----
    FROM python:3.11-slim AS builder

    WORKDIR /app
    
    # Install build tools only in the builder stage
    RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*
    
    COPY requirements.txt .
    RUN pip install --no-cache-dir --user -r requirements.txt
    
    # ---- Stage 2: final ----
    FROM python:3.11-slim

    ENV PYTHONDONTWRITEBYTECODE=1
    ENV PYTHONUNBUFFERED=1
    
    WORKDIR /app
    
    # Create a non-root user (security best practice)
    RUN useradd --create-home appuser
    
    # Copy installed packages from the builder stage
    COPY --from=builder /root/.local /home/appuser/.local
    
    # Copy the app code
    COPY --chown=appuser:appuser . .
    
    # Switch to the non-root user
    USER appuser
    
    # Make sure the user-installed packages are on PATH
    ENV PATH=/home/appuser/.local/bin:$PATH
    
    EXPOSE 5000
    
    CMD ["python", "app.py"]