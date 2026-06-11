FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /data

ENV DATABASE_PATH=/data/bereitschaft.sqlite
ENV APP_PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${APP_PORT} --workers ${GUNICORN_WORKERS:-2} 'app:create_app()'"]
