# Firefox yt-dlp Downloader

This project adds one Firefox toolbar button that sends the current tab URL to a local Python native messaging host. The host starts `yt-dlp` asynchronously and writes downloads to the configured directory with a local timestamp filename such as `2026-08-14_10-47-32.mp4`.

## Configure and install

Edit `DOWNLOAD_DIR` in `native/yt_downloader.py` to an existing or new absolute directory, for example:

```python
DOWNLOAD_DIR = "/home/USER/Videos/downloaded"
```

Then run:

```bash
cd /home/xai/DEV/scriptoza/firefox-yt
./install.sh
```

The installer places the native messaging manifest at `~/.mozilla/native-messaging-hosts/yt_downloader.json` and makes the Python helper executable. It does not require root privileges.

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

Downloaded videos and this source directory are not removed.
