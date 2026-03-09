FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
COPY patchbay/ patchbay/

RUN pip install --no-cache-dir .

EXPOSE 4848

CMD ["patchbay"]
