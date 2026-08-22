# Backend: FastAPI + uvicorn. Sin dependencias de compilacion — por eso el
# driver de MariaDB es PyMySQL (Python puro) y no el conector oficial.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scoutvec/ ./scoutvec/

# no root
RUN useradd --create-home --uid 10001 scout && chown -R scout /app
USER scout

EXPOSE 8000
CMD ["uvicorn", "scoutvec.api:app", "--host", "0.0.0.0", "--port", "8000"]
