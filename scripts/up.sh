#!/bin/sh
# Build and start the stack. USB devices are attached only when the udev symlinks exist.
set -eu
cd "$(dirname "$0")/.."
mkdir -p jobs/timelapses config
./scripts/init-secrets.sh
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
export DIALOUT_GID="$(getent group dialout | cut -d: -f3)"
export VIDEO_GID="$(getent group video | cut -d: -f3)"
set -- -f compose.yaml
if [ -e /dev/carvera ]; then
    set -- "$@" -f compose.machine.yaml
    echo "Carvera serial port: /dev/carvera"
else
    echo "No /dev/carvera yet. The controller will start without the CNC."
fi
if [ -e /dev/carvera-cam ]; then
    set -- "$@" -f compose.camera.yaml
    echo "Camera: /dev/carvera-cam"
else
    echo "No /dev/carvera-cam yet. The camera page will wait for a webcam."
fi
exec docker compose "$@" up -d --build
