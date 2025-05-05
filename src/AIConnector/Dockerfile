FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN python -m venv .venv && \
    . .venv/bin/activate && \
    pip install --upgrade pip && \
    pip install -r requirements.txt

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 5000

#CMD ["python", "main.py"]
