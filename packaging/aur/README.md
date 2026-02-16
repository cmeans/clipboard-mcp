# AUR Package for clipboard-mcp

This directory contains the PKGBUILD for publishing clipboard-mcp to the
[Arch User Repository (AUR)](https://aur.archlinux.org/).

## Prerequisites

- An AUR account with your SSH public key configured
- `base-devel` package group installed
- `python-mcp` must be available (either in AUR or official repos)

## Testing Locally

Build and install the package to verify the PKGBUILD works:

```bash
cd packaging/aur
makepkg -si
```

### Testing in Docker (no clipboard, build validation only)

```bash
docker run --rm -v "$(pwd)/packaging/aur:/pkg" -w /pkg archlinux:latest bash -c '
    pacman -Syu --noconfirm base-devel python python-build python-installer python-wheel python-hatchling &&
    useradd -m builder && chown -R builder: /pkg &&
    su builder -c "makepkg -s --noconfirm"
'
```

### Testing in a VM (full end-to-end with clipboard)

For testing clipboard functionality, use an Arch Linux VM with a graphical
session (Wayland or X11). Install and run:

```bash
makepkg -si
clipboard-mcp --help
```

## Publishing to AUR

1. Generate .SRCINFO:
   ```bash
   makepkg --printsrcinfo > .SRCINFO
   ```

2. Clone the AUR repository:
   ```bash
   git clone ssh://aur@aur.archlinux.org/clipboard-mcp.git /tmp/aur-clipboard-mcp
   ```

3. Copy files and push:
   ```bash
   cp PKGBUILD .SRCINFO /tmp/aur-clipboard-mcp/
   cd /tmp/aur-clipboard-mcp
   git add PKGBUILD .SRCINFO
   git commit -m "Update to version 0.1.1"
   git push
   ```

## Updating

When a new version is released on PyPI:

1. Update `pkgver` and `sha256sums` in `PKGBUILD`.
2. Reset `pkgrel` to `1`.
3. Test with `makepkg -si`.
4. Regenerate `.SRCINFO` and push to AUR.

## Dependency: python-mcp

The `mcp` Python package may not yet be in the official Arch repos or AUR.
If not, you'll need to create a separate `python-mcp` AUR package first,
or change the `depends` to use `python-pip` and install `mcp` via pip
in a post-install hook (less clean but pragmatic).
