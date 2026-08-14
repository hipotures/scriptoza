> **IMPORTANT:** In normal Firefox Release, Mozilla signing may take up to 24 hours. Only the signed `.xpi` can be installed permanently.

# Save This Media

This project adds one Firefox toolbar button. Clicking it sends the active tab URL to a local Python native messaging host, which starts `yt-dlp` and saves the file with a local timestamp filename.

## 1. Requirements

- Linux
- Python 3
- `yt-dlp` available as `yt-dlp` on Firefox's `PATH`
- `zip` for creating the XPI package
- Firefox Release, Firefox Developer Edition, Nightly, or ESR

Check `yt-dlp` before installing:

```bash
command -v yt-dlp
yt-dlp --version
```

## 2. Configure the native helper

Change to the project directory and run the installer:

```bash
cd /home/xai/DEV/scriptoza/firefox-yt
./install.sh
```

The installer:

- creates the configuration outside the repository at `~/.config/firefox-yt-downloader/config`;
- installs the Native Messaging manifest at `~/.mozilla/native-messaging-hosts/yt_downloader.json`;
- makes the helper executable;
- does not require root privileges.

Open the configuration:

```bash
nano ~/.config/firefox-yt-downloader/config
```

Set one line with an absolute path:

```text
DOWNLOAD_DIR=/home/YOUR_USER/Videos/downloaded
```

The directory is created automatically. This file is outside the project and is not committed to Git.

## 3. Create the extension package

Create the XPI for `Save This Media`:

```bash
./package.sh /tmp/firefox-yt.xpi
```

Upload exactly this file to AMO:

```text
/tmp/firefox-yt.xpi
```

Do not upload `manifest.json`, `background.js`, or files from `native/` separately.

## 4. Get a Mozilla signature for normal Firefox

Unsigned extensions cannot be installed permanently in normal Firefox Release.

1. Open <https://addons.mozilla.org/developers/>.
2. Sign in with a Mozilla account or create one.
3. Choose **Submit a New Add-on**.
4. Choose **On your own / Unlisted** distribution.
5. Upload `/tmp/firefox-yt.xpi`.
6. When asked **Do you need to submit source code?**, choose **No**. This extension uses plain JavaScript and has no build or minification process.
7. Leave **Firefox** selected and click **Continue**.
8. Submit the version for signing.
9. Wait for signing. It can take up to 24 hours. Check **Author Hub → My Add-ons** and your spam folder.
10. Download the signed `.xpi` from the Author Hub. Do not reuse the unsigned `/tmp/firefox-yt.xpi`.

## 5. Permanently install the signed extension

1. Open:

   ```text
   about:addons
   ```

2. Click the gear button.
3. Choose **Install Add-on From File...**.
4. Select the downloaded signed `.xpi` file.
5. Accept the installation.

The extension should appear as `Save This Media`. Pin its one toolbar button and click it on a tab whose URL starts with `http://` or `https://`.

## 6. Temporary development test (optional)

This is only for development and is not a permanent installation:

1. Open `about:debugging#/runtime/this-firefox`.
2. Click **Load Temporary Add-on...**.
3. Select:

   ```text
   /home/xai/DEV/scriptoza/firefox-yt/extension/manifest.json
   ```

The temporary extension is unavailable after Firefox restarts.

## 7. Update the extension

After changing the code:

1. Increase `version` in `extension/manifest.json`, for example from `1.0` to `1.1`.
2. Create a new package:

   ```bash
   ./package.sh /tmp/firefox-yt.xpi
   ```

3. Upload the new version in the AMO Author Hub.
4. Wait for signing again and install the downloaded signed XPI.

## 8. Diagnostics and uninstall

Native helper errors are written to:

```text
~/.local/state/firefox-yt-downloader/error.log
```

Syntax checks:

```bash
python3 -m py_compile native/yt_downloader.py
bash -n install.sh uninstall.sh package.sh
```

To remove the extension, remove it through `about:addons`. Then remove Native Messaging:

```bash
./uninstall.sh
```

Downloaded files, `~/.config/firefox-yt-downloader/config`, and the project directory are not removed.
