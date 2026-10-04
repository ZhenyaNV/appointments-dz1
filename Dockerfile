FROM python:3.12.10-slim
WORKDIR /project
COPY requirements.lock.txt .
RUN pip install --no-cache-dir -r requirements.lock.txt
COPY app app
COPY scripts scripts
COPY tests tests
CMD ["python", "-m", "app.main"]
