"""Render host-test HMI commands for layout review, not physical acceptance.

Uses the matching Windows Verdana Bold font; the actual TJC rasterizer may differ.
"""
import argparse
import csv
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def color(value):
    v = int(value)
    return ((v >> 11) * 255 // 31, ((v >> 5) & 63) * 255 // 63, (v & 31) * 255 // 31)


def render(path, font):
    image = Image.new("RGB", (800, 480), "white")
    draw = ImageDraw.Draw(image)
    failures = []
    for command in path.read_text().splitlines():
        kind, _, args = command.partition(" ")
        if kind == "cls":
            draw.rectangle((0, 0, 799, 479), fill=color(args))
            continue
        values = next(csv.reader([args]))
        if kind not in ("fill", "xstr"):
            continue
        x, y, w, h = map(int, values[:4])
        if not (0 <= x <= x+w <= 800 and 0 <= y <= y+h <= 480):
            failures.append({"kind": "bounds", "command": command})
        if kind == "fill":
            draw.rectangle((x, y, x+w-1, y+h-1), fill=color(values[4]))
            continue
        draw.rectangle((x, y, x+w-1, y+h-1), fill=color(values[6]))
        text = values[10]
        lines, line = [], ""
        for word in text.split(" "):
            candidate = (line+" "+word).strip()
            if line and draw.textlength(candidate, font=font) > w:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        if len(lines)*24 > h or any(draw.textlength(line, font=font)>w for line in lines):
            failures.append({"kind": "text_overflow", "text": text, "box": [x,y,w,h]})
        top = y+max(0, (h-len(lines)*24)//2)
        for line in lines:
            length = draw.textlength(line, font=font)
            align = int(values[7])
            left = x if align==0 else x+(w-length)//2 if align==1 else x+w-length
            draw.text((left, top), line, fill=color(values[5]), font=font, anchor="lt")
            top += 24
    target = path.with_suffix(".png")
    image.save(target)
    return image, failures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", default="C:/Windows/Fonts/verdanab.ttf")
    args = parser.parse_args()
    font = ImageFont.truetype(args.font, 24)
    paths = sorted((ROOT/"deploy/artifacts").glob("instrument-screen-commands.txt.page*.txt"))
    if len(paths)!=11:
        raise SystemExit("Run tools/test_instrument_core.py first; expected 11 pages.")
    sheet = Image.new("RGB", (1600, 6*480), "#dee8f2")
    failures = {}
    for i, path in enumerate(paths):
        image, errors = render(path, font)
        sheet.paste(image, ((i%2)*800, (i//2)*480))
        if errors:
            failures[path.name] = errors
    sheet.save(ROOT/"deploy/artifacts/washer-ui-contact-sheet.png")
    (ROOT/"deploy/artifacts/washer-ui-layout-receipt.json").write_text(json.dumps({"pages":11,"errors":failures}, indent=2))
    print(json.dumps({"pages":11,"errors":failures}, indent=2))
    raise SystemExit(bool(failures))


if __name__ == "__main__":
    main()
