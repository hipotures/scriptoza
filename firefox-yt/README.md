# Firefox yt-dlp Downloader

This project adds one Firefox toolbar button that sends the current tab URL to a local Python native messaging host. The host starts `yt-dlp` asynchronously and writes downloads to the configured directory with a local timestamp filename such as `2026-08-14_10-47-32.mp4`.

## Configure and install

Run the installer. It creates the local configuration file `~/.config/firefox-yt-downloader/config` if it does not already exist:

```bash
cd /home/xai/DEV/scriptoza/firefox-yt
./install.sh
```

Edit `~/.config/firefox-yt-downloader/config` and set your existing or new absolute directory:

```text
DOWNLOAD_DIR=/home/USER/Videos/downloaded
```

The configuration file is outside the source project and cannot be included in a Git commit. The installer places the native messaging manifest at `~/.mozilla/native-messaging-hosts/yt_downloader.json` and makes the Python helper executable. It does not require root privileges.

In Firefox, open `about:debugging#/runtime/this-firefox`, click **Load Temporary Add-on...**, and select exactly:

```text
/home/xai/DEV/scriptoza/firefox-yt/extension/manifest.json
```

The extension has no popup or settings page. Click its single toolbar button on a tab whose URL starts with `http://` or `https://` to start the download immediately.

## Permanent installation

The `about:debugging` method is only for development. It is not a permanent installation and the extension is unavailable after Firefox restarts.

Create an XPI package:

```bash
./package.sh /tmp/firefox-yt.xpi
```

For the normal Firefox Release, upload `/tmp/firefox-yt.xpi` to Mozilla Add-ons as an unlisted extension, download the signed XPI, then open `about:addons`, click the gear button, choose **Install Add-on From File...**, and select the signed XPI. Release Firefox requires Mozilla signing for permanent extensions.

For Firefox Developer Edition, Nightly, or ESR, you can install the unsigned package permanently for personal use:

1. Open `about:config` and set `xpinstall.signatures.required` to `false`.
2. Open `about:addons`, click the gear button, choose **Install Add-on From File...**, and select `/tmp/firefox-yt.xpi`.

`yt-dlp` must be installed as an executable named `yt-dlp` on Firefox's `PATH`. Native helper errors are appended to `~/.local/state/firefox-yt-downloader/error.log`; normal downloads produce no helper output.

## Verify the files

```bash
python3 -m py_compile native/yt_downloader.py
bash -n install.sh uninstall.sh
```

After testing, remove only the installed native manifest with:

```bash
./uninstall.sh
```

Downloaded videos, the source directory, and the configuration file are not removed.
