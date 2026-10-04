FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY update_season.py schema.sql ./
ENTRYPOINT ["python", "-u", "/app/update_season.py"]
