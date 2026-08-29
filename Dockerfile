FROM mcr.microsoft.com/playwright/python:v1.62.0-jammy

ENV DEBIAN_FRONTEND=noninteractive
ENV PORT=8080
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["python", "-u", "bot.py"]
