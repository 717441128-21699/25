FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai

RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    pkg-config \
    libfreetype6-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/reports /app/logs /app/templates/agreements /app/archive

EXPOSE 8000

CMD ["sh", "-c", "python init_data.py && uvicorn main:app --host 0.0.0.0 --port 8000"]
