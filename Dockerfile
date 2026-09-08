# Two stages, so the image that runs the work does not carry the tools that
# built it. The wheels are resolved once and copied across.
FROM python:3.12-slim AS build

WORKDIR /build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1

# The locked versions, not the ranges in pyproject.toml. A patch release of some
# dependency changing behaviour is exactly what a deploy must not be exposed to.
COPY requirements.lock.txt ./
#
# Phase 6 packages are declared in pyproject.toml but are missing from
# requirements.lock.txt, which was last regenerated before they were added.
# `modelling.py` imports sklearn at module import time, so without this the
# container crashes before serving anything. Until the lock is regenerated
# from a venv that has them, install them here with pip resolving versions
# against the versions already locked above.
#
# torch comes from its own index, and the CPU build is chosen on purpose:
# the default PyPI wheel is the CUDA build (~4 GB) that this image never runs.
# Plain `pip freeze` would record a version like `2.x.x+cpu` that ordinary
# PyPI cannot install - regenerate with the same index, see DEPLOY.md.
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.lock.txt \
 && /opt/venv/bin/pip install \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple \
      "scikit-learn>=1.5" "sentence-transformers>=3.0"

COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN /opt/venv/bin/pip install --no-deps .


FROM python:3.12-slim AS runtime

RUN useradd --create-home --uid 10001 analysis

ENV PATH=/opt/venv/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# S1: a randomised hash seed changes set and dict iteration order, and that can
# leak into generated output.
ENV PYTHONHASHSEED=0

# Where the data layers live inside the container. The compose file mounts over
# these; nothing here should be taken as a claim about the host.
ENV ANALYSIS_DATA=/data
ENV ANALYSIS_RUNS=/runs

# config/ and prompts/ are read at run time, and here the package is installed
# properly rather than run from a checkout - so it is told where they are
# instead of inferring it from its own location.
ENV ANALYSIS_SYSTEM_ROOT=/app

# The root filesystem is read-only at run time; matplotlib insists on somewhere
# writable for its font cache.
ENV MPLCONFIGDIR=/tmp/matplotlib

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
# Configuration, manifests and prompts are read at run time, so they travel with
# the image rather than being baked into the package.
COPY --chown=analysis:analysis config/ ./config/
COPY --chown=analysis:analysis prompts/ ./prompts/
COPY --chown=analysis:analysis tests/fixtures/ ./tests/fixtures/

# The layer directories are made here so a bare `docker run` has somewhere to
# write, and handed to the user that will do the writing. A mount over any of
# them replaces this, which is the point. Done while still root: / belongs to
# root, so the same commands after USER would fail the build.
RUN mkdir -p /data/raw /data/extracted /data/staging /data/clean /data/mart \
             /data/profile /data/validation /data/artifacts /runs \
 && chown -R analysis:analysis /data /runs

# Never root from here on. The boundary layers are a cooperative sandbox inside
# one process; the user the process runs as is the part the operating system
# enforces.
USER analysis

# Fails loudly when a layer is missing or unreadable, rather than starting a job
# that will die halfway through it.
HEALTHCHECK --interval=1m --timeout=10s --retries=2 \
    CMD ["asys", "check-config"]

ENTRYPOINT ["asys"]
CMD ["--help"]
