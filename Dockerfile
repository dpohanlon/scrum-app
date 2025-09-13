FROM python:3.12-slim

WORKDIR /app

# install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app code
COPY *.py .
COPY assets/ assets/
COPY data/ data/
COPY static/ static/
COPY templates/ templates/

# TfL API key is provided at runtime (e.g. via Docker secret "tfl_app_key")

# start command
CMD gunicorn -b [::]:${PORT:-8080} \
    --worker-class gthread \
    --workers ${WEB_CONCURRENCY:-2} \
    --threads ${THREADS:-8} \
    --timeout ${TIMEOUT:-60} \
    app:app
