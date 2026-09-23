"""Build pixel-exact lossless WebP companions for flood display overlays.

Packed query rasters and other PNG data stay in their original format. Existing
PNG overlays remain as a browser fallback. Identical PNGs share one encoding.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from hashlib import sha256
from pathlib import Path
import json
import shutil
import struct

from PIL import Image, features

ROOT = Path(__file__).resolve().parents[1]
WEBP_MAX_DIMENSION = 16383
# The source rasters are checked-in, trusted data; some exceed Pillow's default
# decompression-bomb threshold despite being valid flood overlay PNGs.
Image.MAX_IMAGE_PIXELS = None


def digest(path):
    h = sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dimensions(path):
    with path.open('rb') as f:
        header = f.read(24)
    if header[:8] != b'\x89PNG\r\n\x1a\n' or header[12:16] != b'IHDR':
        raise RuntimeError(f'Invalid PNG header: {path}')
    return struct.unpack('>II', header[16:24])


def pixel_digest(image):
    h = sha256()
    width, height = image.size
    for top in range(0, height, 64):
        with image.crop((0, top, width, min(height, top + 64))) as stripe:
            h.update(stripe.tobytes())
    return h.digest()


def encode(source, destinations):
    output = destinations[0]
    size = dimensions(source)
    with Image.open(source) as original:
        rgba = original.convert('RGBA')
        pixels = pixel_digest(rgba)
        rgba.save(output, 'WEBP', lossless=True, exact=True, quality=100,
                  method=0 if size[0] * size[1] > 80_000_000 else 4)
    with Image.open(output) as webp:
        decoded = webp.convert('RGBA')
        if decoded.size != size or pixel_digest(decoded) != pixels:
            output.unlink(missing_ok=True)
            raise RuntimeError(f'WebP pixel verification failed: {source}')
    for destination in destinations[1:]:
        shutil.copyfile(output, destination)
    return len(destinations)


def main():
    if not features.check('webp'):
        raise RuntimeError('Pillow was built without WebP support')
    paths = sorted(path for path in (ROOT / 'assets').rglob('*.png')
                   if 'DepthPNGs' in path.parts or 'StagePNGs' in path.parts)
    groups = {}
    unsupported = []
    for path in paths:
        width, height = dimensions(path)
        if width > WEBP_MAX_DIMENSION or height > WEBP_MAX_DIMENSION:
            unsupported.append({'path': str(path.relative_to(ROOT)), 'width': width, 'height': height})
            continue
        target = path.with_suffix('.webp')
        if not target.exists():
            groups.setdefault(digest(path), []).append(path)
    if unsupported:
        (ROOT / 'assets/WebPUnsupportedOverlays.json').write_text(json.dumps({
            'reason': 'Lossless WebP limits each dimension to 16383 pixels; original PNGs remain in use.',
            'files': unsupported
        }, indent=2) + '\n')
    print(f'{len(paths)} display PNGs; {len(unsupported)} over WebP dimension limit; {sum(map(len, groups.values()))} WebP companions missing; {len(groups)} unique encodings', flush=True)
    count = 0
    with ThreadPoolExecutor(max_workers=1) as pool:
        futures = [pool.submit(encode, group[0], [path.with_suffix('.webp') for path in group])
                   for group in groups.values()]
        for future in as_completed(futures):
            count += future.result()
            if count % 100 < 2:
                print(f'Created {count} WebP companions', flush=True)
    print(f'Created {count} pixel-verified WebP companions', flush=True)


if __name__ == '__main__':
    main()
