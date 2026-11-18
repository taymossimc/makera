#!/bin/sh
# Install the USB names /dev/carvera and /dev/carvera-cam.
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
sudo cp "$root/udev/99-carvera.rules" /etc/udev/rules.d/99-carvera.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "Installed udev rules. Replug the CNC or the camera if the symlink is still missing."
