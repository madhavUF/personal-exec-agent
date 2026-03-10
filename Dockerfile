# Personal AI Agent — Docker image
# Build: docker build -t personal-ai-agent .
# Run:   docker run -p 8000:8000 -v $(pwd)/my_data:/app/my_data -v $(pwd)/data:/app/data -e ANTHROPIC_API_KEY=sk-ant-... personal-ai-agent

FROM python:3.11-slim

WORKDIR /app

# System deps for PyMuPDF / docTR if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Default: run FastAPI on 8000
EXPOSE 8000
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
