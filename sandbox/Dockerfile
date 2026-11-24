# Offline sandbox for running test files against originals and mutants.
# Base: official python slim, pinned by registry index digest
# (docker.io/library/python:3.12-slim; linux/arm64 is native on this host).
FROM docker.io/library/python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Every installed package is pinned (incl. transitive deps of pytest, coverage,
# cosmic-ray); --no-deps guarantees nothing outside the lock is pulled in.
COPY requirements.lock /opt/sandbox/requirements.lock
RUN pip install --no-deps -r /opt/sandbox/requirements.lock \
 && pip check \
 && useradd --uid 10001 --create-home --home-dir /home/runner --shell /usr/sbin/nologin runner

USER 10001:10001
ENV HOME=/tmp
WORKDIR /work
CMD ["sleep", "infinity"]
