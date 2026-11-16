# Portable runner: lets the same pipeline run on any free/own machine if GitHub Actions is ever unavailable.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core fontconfig git gh \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt kaggle faster-whisper pytest
COPY . .
ENTRYPOINT ["python", "-m", "nikoblaze"]
CMD ["status"]
