# syntax=docker/dockerfile:1.7
#
# ParrotForwarder v2 container image.
#
# Targets Ubuntu 24.04 ARM64 (the v2 target host). Bakes in the system
# GStreamer stack and pyenv-managed Python 3.11 so the image matches the
# bare-metal install flow. Olympe + protobuf 3.20.3 are installed in a
# dedicated venv. USB passthrough is required at runtime - see the
# "Running" section at the bottom.

ARG UBUNTU_TAG=24.04
FROM ubuntu:${UBUNTU_TAG}

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYENV_ROOT=/opt/pyenv \
    PATH=/opt/pf/.venv/bin:/opt/pyenv/bin:/opt/pyenv/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        iproute2 \
        libbz2-dev \
        libffi-dev \
        libjpeg-dev \
        liblzma-dev \
        libncurses-dev \
        libopencv-dev \
        libreadline-dev \
        libsdl2-2.0-0 \
        libsdl2-dev \
        libsqlite3-dev \
        libssl-dev \
        libxml2-dev \
        libxmlsec1-dev \
        tk-dev \
        xz-utils \
        zlib1g-dev \
        gstreamer1.0-tools \
        gstreamer1.0-plugins-base \
        gstreamer1.0-plugins-good \
        gstreamer1.0-plugins-bad \
        gstreamer1.0-plugins-ugly \
        gstreamer1.0-libav \
        gstreamer1.0-rtsp \
        usbutils \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# pyenv + Python 3.11 (Olympe pin)
# ---------------------------------------------------------------------------

ARG PYENV_VERSION=v2.4.17
ARG PYTHON_VERSION=3.11.10

# -j2 caps the Python source compile at 2 parallel jobs so we do not spike RAM
# on memory-tight builders (Apple Silicon VirtualBox VMs with ~8 GiB get OOM
# thrash otherwise during the pip/Olympe step that follows).
ENV MAKE_OPTS="-j2" \
    MAKEFLAGS="-j2" \
    PYTHON_CONFIGURE_OPTS="--enable-shared"
RUN git clone --branch ${PYENV_VERSION} --depth 1 \
        https://github.com/pyenv/pyenv.git ${PYENV_ROOT} \
    && ${PYENV_ROOT}/bin/pyenv install ${PYTHON_VERSION}

# ---------------------------------------------------------------------------
# Install the package
# ---------------------------------------------------------------------------

WORKDIR /opt/pf
COPY pyproject.toml requirements.txt requirements-dev.txt ./
COPY src/ ./src/
COPY ParrotForwarder.py ./
COPY config.yaml.example ./
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Create the venv and install in three staged RUN layers so pip peak memory
# stays bounded (Olympe pulls heavy wheels; doing it all in one RUN pushed
# an 8 GiB VirtualBox VM into OOM/swap thrash).
# Copy the interpreter into the venv so the non-root runtime user does not
# depend on traversing /root/.pyenv symlinks.
RUN ${PYENV_ROOT}/versions/${PYTHON_VERSION}/bin/python -m venv --copies /opt/pf/.venv \
    && /opt/pf/.venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel
RUN /opt/pf/.venv/bin/pip install --no-cache-dir -e .
RUN /opt/pf/.venv/bin/pip install --no-cache-dir --force-reinstall "protobuf==3.20.3"

# ---------------------------------------------------------------------------
# Non-root user + pre-owned volume paths
# ---------------------------------------------------------------------------

# Some Ubuntu ARM base images already ship a UID 1000 user. Reuse that UID
# instead of failing the image build on a duplicate-ID error.
RUN if ! getent passwd 1000 >/dev/null; then \
        useradd --uid 1000 --create-home --shell /bin/bash parrot; \
    fi \
    && mkdir -p /recordings /var/log/parrot-forwarder /etc/parrot-forwarder \
    && chown -R 1000:1000 /opt/pf /recordings /var/log/parrot-forwarder /etc/parrot-forwarder \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

USER 1000:1000

EXPOSE 8080 8890 12345/udp

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
#
# USB passthrough for the Skycontroller 3 (vendor:product 0430:f001; adjust
# if your device differs):
#
#     docker compose up -d
#
# Preferred invocation. The compose file at the repo root wires USB
# passthrough, host networking, the bind-mounted config directory, and the
# recordings volume that surfaces in the host file system.
#
# One-shot run without compose:
#
#     docker run --rm --name pf \
#         --device=/dev/bus/usb \
#         --network host \
#         --user 1000:1000 \
#         -e PARROT_FORWARDER_SUPERVISOR__HTTP__BIND=0.0.0.0 \
#         -v $(pwd)/config:/etc/parrot-forwarder \
#         -v $(pwd)/recordings:/recordings \
#         ghcr.io/fsabiu/parrot-forwarder:2.0.0
#
# --network host is required so SRT (port 8890) and the dashboard (port 8080)
# are reachable on the LAN without additional port maps.
# --device=/dev/bus/usb grants the container access to the Skycontroller
# USB interface. For tighter scope, use
#
#     --device=/dev/bus/usb/<BUS>/<DEVICE>
#
# and identify the bus/device with `lsusb` before starting the container.
