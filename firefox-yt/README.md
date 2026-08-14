# Firefox yt-dlp Downloader

This project adds one Firefox toolbar button that sends the current tab URL to a local Python native messaging host. The host starts `yt-dlp` asynchronously and writes downloads to the configured directory with a local timestamp filename such as `2026-08-14_10-47-32.mp4`.

## Configure and install

Run the installer. It creates the ignored local configuration file `native/yt_downloader.conf` from the example if it does not already exist:

```bash
cd /home/xai/DEV/scriptoza/firefox-yt
./install.sh
```

Edit `native/yt_downloader.conf` and set your existing or new absolute directory:

```text
DOWNLOAD_DIR=/home/USER/Videos/downloaded
```

The configuration file is ignored by Git and is not part of the public source commit. The installer places the native messaging manifest at `~/.mozilla/native-messaging-hosts/yt_downloader.json` and makes the Python helper executable. It does not require root privileges.

In Firefox, open `about:debugging#/runtime/this-firefox`, click **Load Temporary Add-on...**, and select exactly:

```text
/home/xai/DEV/scriptoza/firefox-yt/extension/manifest.json
```

The extension has no popup or settings page. Click its single toolbar button on a tab whose URL starts with `http://` or `https://` to start the download immediately.

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

Downloaded videos, the source directory, and the ignored configuration file are not removed.
