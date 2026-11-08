FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY campus_app campus_app
COPY public public
ENV DATA_DIR=/app/data
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "campus_app.main:app", "--host", "0.0.0.0", "--port", "8080"]
