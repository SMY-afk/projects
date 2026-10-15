FROM python:3.12-slim

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
RUN /opt/venv/bin/python -m pip install --no-cache-dir ".[dev]"

COPY app/parsers ./app/parsers
COPY backend/app ./backend/app
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["/opt/venv/bin/python", "-m", "erp_api"]
