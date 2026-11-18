# Source build of the Carvera Community Controller fork.
# The upstream image copies a prebuilt AppImage, which would hide this fork's
# job-state changes, so the container runs the Python package directly.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    KIVY_GL_BACKEND=sdl2

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-dev \
        python3-pip \
        python3-venv \
        ca-certificates \
        locales \
        tigervnc-standalone-server \
        openbox \
        supervisor \
        novnc \
        websockify \
        libgl1 \
        libglib2.0-0 \
        libsdl2-2.0-0 \
        libsdl2-image-2.0-0 \
        libsdl2-ttf-2.0-0 \
        libsdl2-mixer-2.0-0 \
        libmtdev1 \
        libhidapi-hidraw0 \
        gstreamer1.0-plugins-base \
        fonts-dejavu-core \
        build-essential \
        libhidapi-dev \
    && sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen \
    && locale-gen \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/carvera
RUN /opt/carvera/bin/pip install --upgrade pip \
    && /opt/carvera/bin/pip install \
        "Kivy>=2.3.1,<2.4" \
        "pyserial>=3.5" \
        "pyquicklz>=1.4.1" \
        "hid>=1.0.7" \
        "ezdxf>=1.3.0" \
        "certifi>=2017.4.17"

WORKDIR /opt/carvera-src
COPY controller/carveracontroller /opt/carvera-src/carveracontroller
COPY docker/supervisord.conf /etc/supervisor/conf.d/carvera.conf

ENV PYTHONPATH=/opt/carvera-src \
    HOME=/config \
    DISPLAY=:0 \
    CARVERA_JOBS_DIR=/jobs \
    CARVERA_JOB_STATE=/config/job-state.json

EXPOSE 5900 8080
VOLUME ["/config", "/jobs"]

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/carvera.conf"]
