FROM python:3.15-slim@sha256:94d3426f1def7db4a106a232ac121bfd975393e5dfd40a619b955fae45fe7913

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY requirements.txt ./
COPY src ./src
COPY ops ./ops
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

ENTRYPOINT ["python", "-m", "ops.worker.container_runtime"]
