# The mock PSP and the experiment runner share one image: the suite imports the
# same holdspec package the service does, so a version skew between them is
# impossible by construction.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY docker ./docker
COPY experiments ./experiments
COPY spec ./spec
COPY tests ./tests

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

CMD ["python", "docker/mock_psp/app.py"]
