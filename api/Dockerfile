FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev libmagic1 tesseract-ocr && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Presidio's default NLP engine lazily downloads this (~400MB) from GitHub on first use
# otherwise - confirmed for real against the deployed app: a fresh container's first
# document upload hung for ~30s downloading+installing it mid-request (a real ALB/
# CloudFront/browser timeout risk, and it repeats on every redeploy, not just once ever,
# since each new container starts from a fresh filesystem). Baking it into the image
# means it's on disk before the container ever starts.
RUN python -m spacy download en_core_web_lg

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
