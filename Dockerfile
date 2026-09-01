FROM python:3.14-slim@sha256:656d12e70054d5fda18a045e2494c96701e9792dd1445f95b3d038df954f57e9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
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

EXPOSE 8000
CMD ["uvicorn", "pipelens.main:app", "--host", "0.0.0.0", "--port", "8000"]
