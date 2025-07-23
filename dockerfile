FROM python:3.11-slim
RUN apt-get update && apt-get install -y \
    wget \
    software-properties-common \
    musescore3 \
    xvfb \
    libglib2.0-0 \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libgtk-3-0 \
    libgbm1 \
    libasound2 \
    procps \
    tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8129
ENV QT_QPA_PLATFORM=offscreen
ENV DISPLAY=:99
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["tini", "--"]
CMD ["python", "app.py"]
