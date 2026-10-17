FROM python:3.13-slim
RUN pip install --no-cache-dir redis==5.2.1
WORKDIR /app
COPY api.py worker.py ./
