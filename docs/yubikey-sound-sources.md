# YubiKey notification sound sources

Download these sounds manually after reinstalling the system. The audio files are not stored in this repository.

Provider: Pixabay. Author: Universfield.

| Event | Title | Pixabay asset ID | Required local filename | Download page |
| --- | --- | --- | --- | --- |
| Touch requested | New Notification 066 | 494545 | `universfield-new-notification-066-494545.mp3` | https://pixabay.com/sound-effects/technology-new-notification-066-494545/ |
| Touch waiting ended | New Notification 064 | 494547 | `universfield-new-notification-064-494547.mp3` | https://pixabay.com/sound-effects/technology-new-notification-064-494547/ |

The title numbers (`066`, `064`) differ from the Pixabay asset IDs (`494545`, `494547`). These source pages match the installed filenames; the local MP3s have no metadata tags and have not been compared byte-for-byte with fresh downloads.

## Restore after reinstalling

1. Open each download page and download the MP3 manually.
2. Create `~/.local/share/sounds/` if necessary and place both files there using the exact filenames above. Rename downloads if Pixabay supplies different filenames.
3. Install the script and user service from the repository root:

   ```bash
   python3 utils/install.py --run
   systemctl --user daemon-reload
   systemctl --user enable --now yubikey-touch-sound.service
   ```

Requires Python 3, `ffplay` (FFmpeg), and a working `yubikey-touch-detector` user service exposing its Unix socket. Playback volume is set to 15% in `utils/yubikey_touch_sound.py`. A touch-waiting-ended event does not prove successful authentication.

License reference: https://pixabay.com/service/license-summary/ (reference link only; no audio or license file is bundled).
