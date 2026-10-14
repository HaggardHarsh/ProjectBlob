FROM docker.io/library/python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY hermes /opt/hermes
RUN python -m pip install --no-cache-dir --editable /opt/hermes \
    && groupadd --gid 1000 blob \
    && useradd --uid 1000 --gid 1000 --create-home blob
COPY hermes_worker.py openshell_worker.py /opt/blob/
USER 1000:1000
WORKDIR /tmp
CMD ["/usr/bin/sleep", "infinity"]
