# Start the worker after Android reboots

This setup uses the official Termux:Boot add-on. The worker remains in dry-run mode by default.

## Install

1. Install **Termux:Boot** from the same trusted source as Termux, normally F-Droid.
2. Open the Termux:Boot app once so Android permits it to receive boot events.
3. In Termux, update the repository and install the launcher:

```bash
cd ~/compliant-social-bot
git pull
chmod +x deploy/termux/install-boot.sh
deploy/termux/install-boot.sh
```

4. Exclude both **Termux** and **Termux:Boot** from Android battery optimization.
5. Reboot the phone and wait about 30 seconds.
6. Verify from Termux:

```bash
cd ~/compliant-social-bot
deploy/termux/workerctl status
cat data/termux-boot.log
```

## Behavior

- waits 20 seconds after boot before starting
- does not create a duplicate worker if one is already running
- records boot activity in `data/termux-boot.log`
- delegates process management to `deploy/termux/workerctl`
- keeps live publication disabled unless the control script is explicitly started with `--live`

Override the boot delay by editing the generated launcher in `~/.termux/boot/compliant-social-bot` and setting `BOOT_DELAY_SECONDS` before executing `boot-start.sh`.

Android vendors may still stop background apps aggressively. A wake lock helps, but disabling battery optimization is still important for unattended operation.
