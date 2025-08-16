FROM python:3.10

# Install system dependencies... (Keep this)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    espeak-ng \
    # Chrome dependencies
    wget \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Chrome (Keep this)
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && sh -c 'echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list' \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# !!! ChromeDriver installation section is REMOVED !!!

# Set display port (Keep this)
ENV DISPLAY=:99

WORKDIR /app

COPY requirements.txt .
# Upgrade pip and install requirements (Keep this)
RUN pip install --no-cache-dir --upgrade pip
# This will now install webdriver-manager too
#RUN pip install --no-cache-dir -r requirements.txt
ARG CUDA_COMPUTE_CAPABILITIES=75
ENV CMAKE_ARGS=""
# If no CUDA/GPU, use: ENV CMAKE_ARGS=""

# Force reinstall to pick up CMAKE_ARGS, install AFTER setting ENV VAR
RUN pip install --no-cache-dir -r requirements.txt
# Copy application code (Keep this)
COPY . .

# Create static directory (Keep this)
RUN mkdir -p static

EXPOSE 8000

# Start FastAPI app (Keep this)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]