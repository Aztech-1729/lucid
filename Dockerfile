FROM python:3.12-slim

WORKDIR /app

# System deps (qrcode/pillow may need libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all source files
COPY . .

# Remove unnecessary files
RUN rm -rf .git .gitignore bot.log requirements.txt pyproject.toml 2>/dev/null

CMD ["python", "main.py"]
