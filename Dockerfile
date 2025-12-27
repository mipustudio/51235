FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей для Pillow и других библиотек
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    python3-dev \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем requirements и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Создаем директорию для данных
RUN mkdir -p /app/data && chmod 777 /app/data

CMD ["python", "bot.py"]
