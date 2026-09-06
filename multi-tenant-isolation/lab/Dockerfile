FROM python:3.12-slim

# Pinned: an isolation lab whose result depends on which driver version got
# resolved that day is not evidence of anything.
RUN pip install --no-cache-dir "psycopg[binary]==3.2.3"

WORKDIR /app
COPY app/ /app/
ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/vulnerable.py"]
