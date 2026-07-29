"""Finder presentation for the macOS drag-to-install disk image."""
import os


application = defines["app"]
application_name = os.path.basename(application)

format = "UDZO"
files = [application]
symlinks = {"Applications": "/Applications"}

background = None
window_rect = ((200, 200), (660, 400))
icon_size = 128
icon_locations = {
    application_name: (180, 200),
    "Applications": (480, 200),
}
