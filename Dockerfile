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
    PATH=/opt/pf/.venv/bin:/root/.pyenv/bin:/root/.pyenv/shims:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
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

RUN git clone --branch ${PYENV_VERSION} --depth 1 \
        https://github.com/pyenv/pyenv.git /root/.pyenv \
    && /root/.pyenv/bin/pyenv install ${PYTHON_VERSION}

# ---------------------------------------------------------------------------
# Install the package
# ---------------------------------------------------------------------------

WORKDIR /opt/pf
COPY pyproject.toml requirements.txt requirements-dev.txt ./
COPY src/ ./src/
COPY ParrotForwarder.py ./
COPY config.yaml.example ./

# Create the venv, install runtime deps (incl. Olympe), force-pin protobuf,
# install the package in editable mode.
RUN /root/.pyenv/versions/${PYTHON_VERSION}/bin/python -m venv /opt/pf/.venv \
    && /opt/pf/.venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/pf/.venv/bin/pip install --no-cache-dir -e . \
    && /opt/pf/.venv/bin/pip install --no-cache-dir --force-reinstall "protobuf==3.20.3"

# Seed default config if none is mounted in at runtime.
RUN mkdir -p /etc/parrot-forwarder \
    && cp config.yaml.example /etc/parrot-forwarder/config.yaml

EXPOSE 8080 8890 12345/udp

ENTRYPOINT ["/opt/pf/.venv/bin/parrot-forwarder-supervisor", "--config", "/etc/parrot-forwarder/config.yaml"]

# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
#
# USB passthrough for the Skycontroller 3 (vendor:product 0430:f001; adjust
# if your device differs):
#
#     docker run --rm --name pf \
#         --device=/dev/bus/usb \
#         --network host \
#         -e PARROT_FORWARDER_SUPERVISOR__HTTP__BIND=0.0.0.0 \
#         -v /etc/parrot-forwarder/config.yaml:/etc/parrot-forwarder/config.yaml:ro \
#         ghcr.io/fsabiu/parrot-forwarder:2.0.0
#
# --network host is required so SRT (port 8890) and the dashboard (port 8080)
# are reachable on the LAN without additional port maps.
# --device=/dev/bus/usb grants the container access to the Skycontroller
# USB interface. If you want tighter scope, use
#
#     --device=/dev/bus/usb/<BUS>/<DEVICE>
#
# and identify the bus/device with `lsusb` before starting the container.
