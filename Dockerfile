FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system pipelens \
    && useradd --system --gid pipelens --home-dir /app --no-create-home \
        --shell /usr/sbin/nologin pipelens \
    && pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements.txt \
    && python -m pip uninstall --yes pip setuptools \
    && chown -R pipelens:pipelens /app

USER pipelens

EXPOSE 8000
CMD ["uvicorn", "pipelens.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
