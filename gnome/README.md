# GNOME Extensions

## rTorrent Status

`rtorrent-status/` is a GNOME Shell 50/51 extension written in JavaScript/GJS. It monitors a local or remote `rtorrent` instance over SCGI JSON-RPC and displays torrent states in the top panel using the same dot-and-menu layout as `agentai-status/`.

### Requirements

- GNOME Shell 50 or 51
- `rtorrent` with SCGI RPC enabled:
  - Modern `rtorrent` (0.9.7+ / 0.16.x) in `~/.config/rtorrent/rtorrent.rc`:
    ```ini
    network.rpc.use_xmlrpc.set = true
    network.rpc.use_jsonrpc.set = true
    network.scgi.open_port = "127.0.0.1:5000"
    ```
  - Legacy `rtorrent` (0.8.x, e.g. older Ubuntu) in `~/.rtorrent.rc`:
    ```ini
    scgi_port = 127.0.0.1:5000
    ```
  The widget automatically detects JSON-RPC, XML-RPC `d.multicall2`, and legacy XML-RPC `d.multicall`.

### Configuration

The widget reads `~/.config/scriptoza/rtorrent-status.json` (or `$XDG_CONFIG_HOME/scriptoza/rtorrent-status.json`) on each poll:

```json
{
  "name": "rtorrent",
  "host": "127.0.0.1",
  "port": 5000,
  "pollSeconds": 3,
  "density": "large"
}
```

Change `name`, `host`, `port`, or `pollSeconds` when customizing the panel hover label or pointing the widget at a remote server (for example over a VPN or SSH tunnel). Changes take effect automatically on the next poll.

### Installation

```bash
bash gnome/install_rtorrent_status.sh
```

Log out and log back in after installing for the first time. For an already loaded widget, update the installed files and reload the panel module in Looking Glass (`Alt+F2` -> `lg`):

```javascript
await (await import('file:///home/user/.local/share/gnome-shell/extensions/rtorrent-status@scriptoza/reload.js')).reload()
```

### States

| State | Color | Meaning |
| --- | --- | --- |
| `error` | Blinking red | Non-empty `d.message` (tracker or disk error) |
| `hashing` | Yellow | Checking file hashes (`d.hashing > 0`) |
| `downloading` | Blue | Active incomplete torrent |
| `seeding` | Green | Active completed torrent |
| `paused` | Gray | Inactive / paused torrent |

The footer displays total download and upload rates, the last update timestamp, the widget version, and a density toggle (`large`, `medium`, `compact`).
