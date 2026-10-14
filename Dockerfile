# Optional API image. The local demo does not need Docker.
FROM python:3.11-slim
WORKDIR /srv
COPY backend /srv/backend
COPY README.md /srv/README.md
RUN pip install --no-cache-dir "/srv/backend"
WORKDIR /srv/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
