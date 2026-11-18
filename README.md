# Makera

A public, containerized controller for a [Makera Carvera](https://www.makeracnc.com/) (and Carvera Air) that can sit on a touchscreen next to the machine.

It runs a fork of the [Carvera Community Controller](https://github.com/Carvera-Community/Carvera_Controller) and adds three things around it:

- A logged-in page on the local network, so a laptop can open the same UI the touchscreen shows.
- A host folder, `jobs/`, for G-code. The controller's file browser opens there, and the files stay on the machine when the container is recreated.
- Webcam timelapses written into `jobs/timelapses/` when a program starts, and encoded when it stops.

The controller itself is [github.com/taymossimc/Carvera_Controller](https://github.com/taymossimc/Carvera_Controller), branch `palamedes`. `upstream` should stay pointed at `Carvera-Community/Carvera_Controller`. Both repositories are GPL-2.0.

## What you need

- A 64-bit Linux host with Docker. The reference machine is an NVIDIA Jetson Orin NX running Ubuntu 22.04. The controller container is Ubuntu 24.04, so the host can stay on 22.04.
- A Carvera or Carvera Air on USB. The board is an FTDI serial device (`0403:6001`).
- Optional: a USB webcam, and an HDMI touchscreen. The reference panel is a Waveshare 10.1 inch capacitive display (HDMI for the picture, USB for touch). Some Orin carrier boards have DisplayPort instead of HDMI; use a DP-to-HDMI adapter in that case.

The Carvera's own power switch and E-stop remain the safety path. This software can jog and run the machine. Do not leave it unattended, and do not flash firmware from this stack.

The community controller's built-in timelapse switch is for a Makera Z1 camera. It is not used here.

## Layout

| Path | What it is |
|---|---|
| `jobs/` | G-code and other job files, mounted into the controller at `/jobs` |
| `jobs/timelapses/` | Finished `.mp4` files and a `.json` note of which job they belong to |
| `config/` | Controller settings and `job-state.json` |
| `secrets/caddy.env` | LAN username and password hash. Not committed |

Drop a file such as `jobs/bracket.nc` on the host. In the controller, upload it from the Jobs folder. When that program runs, the movie is saved as `jobs/timelapses/bracket-<timestamp>.mp4`.

## Run

```bash
git clone --recurse-submodules https://github.com/taymossimc/makera.git
cd makera
./scripts/install-udev.sh
./scripts/up.sh
```

`scripts/up.sh` creates a random LAN password the first time and prints it. The login user is `carvera`. Open:

- On this computer, with no password: `http://127.0.0.1:8080`
- From another device on the LAN: `https://<this-host>:8443`

The first visit warns until you trust the certificate in `secrets/tls/`. That certificate is created for this computer's name and current addresses. If the address changes, delete `secrets/tls` and run `scripts/up.sh` again.

Replug the CNC after installing the udev rule, then run `scripts/up.sh` again so `/dev/carvera` is passed into the container. The same applies to `/dev/carvera-cam`. In the controller, connect with the USB menu. If the port is not listed, the manual device path is `/dev/carvera`.

To pick up later community-controller releases:

```bash
cd controller
git remote add upstream https://github.com/Carvera-Community/Carvera_Controller.git
git fetch upstream
git merge upstream/main
```

## Touchscreen

The panel is a normal HDMI display plus a USB touch device. The pixels stay on the host; the container does not take over the Jetson display.

When a monitor is connected and a graphical session exists:

```bash
sudo cp systemd/carvera-kiosk@.service /etc/systemd/system/
sudo systemctl enable --now carvera-kiosk@<your-user>
```

Chromium opens `http://127.0.0.1:8080` fullscreen. That page is not the logged-in one. Standing at the machine is the access check. Ubuntu on Jetson reports single-point touch for this panel, which is enough for the kiosk.

If the picture flickers, power the panel from a 5 V 3 A supply and leave the touch cable on the computer.

## Timelapse

The fork writes `config/job-state.json` when playback starts, pauses, halts, or goes idle. The timelapse container reads that file. It grabs a 1280×720 frame every 2 seconds while `playing` is true, then encodes H.264 at 30 fps, so one hour of cutting becomes about one minute of video. Frames are deleted after a successful encode. Movies are pruned when `jobs/timelapses/` grows past 8 GB.

The camera page can force recording on or off. Those buttons override the job signal until you choose "Follow the job" again.

If `job-state.json` is missing, the camera falls back to recording while the picture is changing and closes the clip after the scene has been still for 3 minutes. Someone walking past the camera can start a clip in that mode.

## Ports

| Port | Who can open it |
|---|---|
| `127.0.0.1:8080` | Controller UI, no login. Used by the touchscreen |
| `127.0.0.1:5900` | VNC, no password |
| `8443` | LAN, username and password, controller at `/` and camera at `/cam/` |
