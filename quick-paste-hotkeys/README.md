# Quick-Paste Hotkeys

A tiny [Hammerspoon](https://www.hammerspoon.org/) config that binds a global
keyboard shortcut to each link you have to paste over and over during job
applications — LinkedIn, GitHub, portfolio, etc. Press the hotkey, the URL
types itself into whatever field is focused. No more open-profile →
copy-URL → alt-tab → paste.

## Setup

1. Install [Hammerspoon](https://www.hammerspoon.org/) (free, open source).
2. Copy `init.lua` to `~/.hammerspoon/init.lua`.
3. Launch Hammerspoon and grant it Accessibility permission when prompted
   (System Settings → Privacy & Security → Accessibility) — required for it
   to type into other apps.
4. Reload the config from the Hammerspoon menu-bar icon.

## Usage

| Hotkey | Pastes |
|---|---|
| `⌘⌃L` | LinkedIn profile |
| `⌘⌃G` | GitHub profile |

## Customizing

Add more links by adding entries to the `profileLinks` table in `init.lua`:

```lua
{ key = "p", label = "Portfolio", text = "https://your-site.com" },
```

Any single letter works as `key` (paired with `⌘⌃`), and `text` can be any
string — a URL, phone number, or boilerplate cover-note line.
