# The libraries and the application are built apart, because they change at
# very different rates: the libraries when the lock changes, the application on
# every edit. Copying one venv that held both made each edit write a fresh
# 2.3 GB layer, and the build cache kept every one of them (81 GB by
# 2026-09-13). tests/unit/test_dockerfile_layers.py holds this order in place.

# Only the dependency list is read out of pyproject.toml. The stage below copies
# the list, not the file, so editing tool settings in pyproject.toml does not
# reinstall torch.
FROM python:3.12-slim AS dep-list
WORKDIR /build
COPY pyproject.toml ./
RUN python -c "import tomllib; print(chr(10).join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))" > deps.txt


FROM python:3.12-slim AS deps

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

# The lock predates some runtime dependencies (including the dashboard).
# Resolve every declared dependency while preserving the locked versions and
# using CPU wheels for torch.
COPY --from=dep-list /build/deps.txt ./
RUN /opt/venv/bin/pip install -c requirements.lock.txt \
      --index-url https://download.pytorch.org/whl/cpu \
      --extra-index-url https://pypi.org/simple -r deps.txt


# The application alone, as a wheel. Nothing from here is copied into the
# runtime venv wholesale, so an edit under src/ never rewrites the libraries.
FROM deps AS app
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN /opt/venv/bin/pip wheel --no-deps --wheel-dir /wheels .


FROM python:3.12-slim AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      tesseract-ocr \
      tesseract-ocr-vie \
 && rm -rf /var/lib/apt/lists/*

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

COPY --from=deps /opt/venv /opt/venv

# The application goes in on its own, after the libraries: an edit rewrites
# this layer of a few MB and leaves the 2.3 GB one above it untouched. The
# wheel is mounted rather than copied, so it leaves no layer of its own. Fails
# the build if the installed app cannot load.
RUN --mount=type=bind,from=app,source=/wheels,target=/tmp/wheels \
    /opt/venv/bin/pip install --no-cache-dir --no-deps --no-index /tmp/wheels/*.whl \
 && /opt/venv/bin/pip check \
 && /opt/venv/bin/python -c "import analysis_system.cli; import analysis_system.api.app; import uvicorn; import python_multipart"

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
