#!/usr/bin/env python3
"""Generate the weather and parameter icons used by the widget.

Two backends are available:

``diffusers`` (default)
    Runs Z-Image-Turbo locally through PyTorch on Apple Silicon. This is the
    same model that is available for Ollama, but it works even when the
    installed Ollama build has image generation turned off.

``ollama``
    Calls an image model through the Ollama HTTP API.

In both cases the result is cleaned up: the background is removed, the
artwork is trimmed to its bounding box, centred on a square canvas and saved
as a PNG with an alpha channel, so it works on the light and the dark theme.

    python make_icons.py                      # generate everything
    python make_icons.py sun rain             # only these two
    python make_icons.py --list               # show what would be generated
    python make_icons.py --backend ollama     # use Ollama instead
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

import numpy as np
from PIL import Image

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_IMAGE_MODEL", "jmorgan/z-image-turbo:fp8")
DIFFUSERS_MODEL = os.environ.get("DIFFUSERS_IMAGE_MODEL", "Tongyi-MAI/Z-Image-Turbo")
OUTPUT_DIR = os.environ.get("ICON_DIR", "assets/icons")
SIZE = 256
RESOLUTION = 1024

STYLE = (
    "flat vector illustration, modern app icon design, bold rounded shapes, "
    "flat vibrant colours, high contrast, clean and modern, single centred "
    "subject filling the frame, isolated on a plain solid white background, "
    "no text, no letters, no numbers, no border, no frame, no drop shadow, "
    "square icon"
)

#: key -> prompt describing what to draw.
ICONS: dict[str, str] = {
    # Weather conditions.
    "sun": "a bright cheerful yellow sun with a warm orange glow and short rounded rays",
    "partly": "a yellow sun peeking out from behind a soft white fluffy cloud",
    "cloud": "a single soft white fluffy cloud",
    "rain": "a light grey cloud with several blue raindrops falling below it",
    "snow": "a white cloud with pale blue snowflakes falling below it",
    "sleet": "a grey cloud with both blue raindrops and white snowflakes falling",
    "storm": "a dark charcoal storm cloud with a bright yellow lightning bolt",
    "wind": "three curved blue wind swirls blowing sideways",
    # Parameters.
    "thermo": "a red liquid thermometer standing upright",
    "drop": "a single glossy blue water droplet",
    "gauge": "a round blue pressure gauge dial with a needle",
    "rain-drop": "a large blue raindrop with a small splash underneath",
    "cloud-cover": "a bright white cloud with a small blue sky behind it",
    "feels": "a red thermometer wrapped in a small blue scarf",
    "gust": "three strong curved teal wind gust lines blowing hard",
}

# Icons that are not generated with the model. The fog symbol is white on
# white, which the background removal cannot handle, so it stays drawn.
DRAWN_ONLY = ("fog",)


# --------------------------------------------------------------------------- #
# Backends
# --------------------------------------------------------------------------- #


def generate_ollama(prompt: str, model: str = OLLAMA_MODEL, timeout: int = 900) -> Image.Image:
    """Ask an Ollama image model for one image."""
    payload = {
        "model": model,
        "prompt": f"{prompt}. {STYLE}",
        "stream": False,
        "options": {"num_predict": 8, "temperature": 0.4},
    }
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = json.load(response)

    images = body.get("images") or []
    if not images:
        raise RuntimeError(f"no image in the response: {str(body)[:300]}")
    return Image.open(io.BytesIO(base64.b64decode(images[0]))).convert("RGB")


class DiffusersBackend:
    """Z-Image-Turbo running on Apple Silicon through PyTorch."""

    def __init__(self, model: str = DIFFUSERS_MODEL):
        import torch
        from diffusers import ZImagePipeline

        self.torch = torch
        dtype = torch.bfloat16 if torch.backends.mps.is_available() else torch.float16
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        print(f"loading {model} on {device} ({dtype})", flush=True)
        self.pipe = ZImagePipeline.from_pretrained(model, torch_dtype=dtype)
        self.pipe = self.pipe.to(device)
        self.pipe.set_progress_bar_config(disable=True)
        self.device = device

    def generate(self, prompt: str) -> Image.Image:
        image = self.pipe(
            prompt=f"{prompt}. {STYLE}",
            num_inference_steps=8,
            guidance_scale=0.0,
            width=RESOLUTION,
            height=RESOLUTION,
        ).images[0]
        return image.convert("RGB")


# --------------------------------------------------------------------------- #
# Cleaning up
# --------------------------------------------------------------------------- #


def _corner_colour(array: np.ndarray) -> np.ndarray:
    """Average colour of the four corners, used as the background colour."""
    h, w, _ = array.shape
    size = max(2, min(h, w) // 40)
    corners = np.concatenate(
        [
            array[:size, :size].reshape(-1, 3),
            array[:size, -size:].reshape(-1, 3),
            array[-size:, :size].reshape(-1, 3),
            array[-size:, -size:].reshape(-1, 3),
        ]
    )
    return np.median(corners, axis=0)


def remove_background(image: Image.Image, tolerance: int = 38) -> Image.Image:
    """Make the background transparent.

    The background is the colour of the corners. The flood fill starts at the
    border and only spreads over pixels that are close to that colour, so
    white areas inside the artwork are kept.
    """
    array = np.array(image.convert("RGB")).astype(np.int16)
    background = _corner_colour(array)
    distance = np.abs(array - background).sum(axis=2)
    close = distance < tolerance * 3

    height, width = close.shape
    reachable = np.zeros_like(close)
    reachable[0, :] |= close[0, :]
    reachable[-1, :] |= close[-1, :]
    reachable[:, 0] |= close[:, 0]
    reachable[:, -1] |= close[:, -1]

    # Grow the reachable region over the connected background.
    for _ in range(max(height, width)):
        grown = reachable.copy()
        grown[1:, :] |= reachable[:-1, :]
        grown[:-1, :] |= reachable[1:, :]
        grown[:, 1:] |= reachable[:, :-1]
        grown[:, :-1] |= reachable[:, 1:]
        grown &= close
        if np.array_equal(grown, reachable):
            break
        reachable = grown

    alpha = np.where(reachable, 0, 255).astype(np.uint8)
    result = image.convert("RGBA")
    result.putalpha(Image.fromarray(alpha))
    return result


def trim(image: Image.Image, padding: int = 12) -> Image.Image:
    """Cut to the artwork and centre it on a square canvas."""
    bbox = image.getbbox()
    if not bbox:
        return image
    artwork = image.crop(bbox)

    side = max(artwork.width, artwork.height) + 2 * padding
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(
        artwork,
        ((side - artwork.width) // 2, (side - artwork.height) // 2),
        artwork,
    )
    return canvas


def finish(image: Image.Image, size: int = SIZE) -> Image.Image:
    """Remove the background, trim and resize."""
    return trim(remove_background(image)).resize((size, size), Image.LANCZOS)


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("keys", nargs="*", help="icons to generate (default: all)")
    parser.add_argument("--list", action="store_true", help="list the known icons and exit")
    parser.add_argument("--backend", default="diffusers", choices=["diffusers", "ollama"])
    parser.add_argument("--model", help="model to use")
    parser.add_argument("--out", default=OUTPUT_DIR, help="output directory")
    parser.add_argument("--force", action="store_true", help="regenerate icons that already exist")
    args = parser.parse_args(argv)

    if args.list:
        for key, prompt in ICONS.items():
            print(f"{key:14s} {prompt}")
        return 0

    keys = args.keys or list(ICONS)
    unknown = [key for key in keys if key not in ICONS]
    if unknown:
        print(f"unknown icon(s): {', '.join(unknown)}", file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    manifest_path = os.path.join(args.out, "manifest.json")
    manifest = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as handle:
            manifest = json.load(handle)

    backend = None
    if args.backend == "diffusers":
        backend = DiffusersBackend(args.model or DIFFUSERS_MODEL)

    for key in keys:
        target = os.path.join(args.out, f"{key}.png")
        if os.path.exists(target) and not args.force and not args.keys:
            print(f"{key}: already there")
            continue
        print(f"{key}: generating...", flush=True)
        started = time.time()
        try:
            if backend is not None:
                raw = backend.generate(ICONS[key])
            else:
                raw = generate_ollama(ICONS[key], args.model or OLLAMA_MODEL)
        except Exception as exc:  # noqa: BLE001 - one failure should not stop the rest
            print(f"{key}: failed ({exc})", file=sys.stderr)
            continue
        finish(raw).save(target)
        manifest[key] = os.path.basename(target)
        with open(manifest_path, "w") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
        print(f"{key}: {target} ({time.time() - started:.1f}s)", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
