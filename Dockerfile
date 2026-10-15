FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUTF8=1 PYTHONIOENCODING=utf-8
COPY pyproject.toml README.md ./
COPY app ./app
COPY docs_tz/registrature_reglament.docx ./docs_tz/registrature_reglament.docx
RUN pip install --no-cache-dir .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
