FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY ops ./ops
RUN apt-get update \
    && apt-get upgrade --yes \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system pipelens \
    && useradd --system --gid pipelens --home-dir /app --no-create-home \
        --shell /usr/sbin/nologin pipelens \
    && pip install --no-cache-dir . \
    && python -m pip uninstall --yes pip setuptools \
    && chown -R pipelens:pipelens /app

USER pipelens

ENTRYPOINT ["python", "-m", "ops.worker.container_runtime"]
