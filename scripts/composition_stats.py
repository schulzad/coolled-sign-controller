"""Statistics for an agent-drawn composition, kept the same way for every piece so pieces can be compared.

Three layers, each read only from what is there:
- the scene: canvas, frames, colours, lit pixels, sprites, placements, characters, and how much of the
  picture brushes baked versus what was painted by hand (a sprite counts as baked when a note on it or
  on one of its placements says "baked by");
- the composition folder, when the scene sits in one like examples/canvas/ringed-planet: looks taken and
  at what scales, saved versions, and the changes and traces its log.txt records;
- the session that painted it, given the agent's transcript: tool calls by tool, pictures read, the text
  the agent generated, and wall-clock time. Token counts are estimates: about 4 characters per token for
  text, and width x height / 750 for a picture, as Anthropic documents for image input. Text counts
  the agent's messages together with the reasoning the transcript records. Input tokens, the context
  re-read on every call, are the larger cost and the transcript cannot say how many there were.

Usage:
    python scripts/composition_stats.py examples/scenes/*.json examples/canvas/*/scene.json
    python scripts/composition_stats.py examples/canvas/ringed-planet/scene.json --write \\
        --transcript ~/.cursor/projects/<project>/agent-transcripts/<id>/<id>.jsonl \\
        --session-start "go for it" --ended 2026-10-31T00:50-05:00
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from opensign.animation.scene import compile_scene

PANEL = (64, 16)
NAMES = {
    (0, 0, 0): "black", (255, 0, 0): "red", (0, 255, 0): "green", (0, 0, 255): "blue",
    (0, 255, 255): "cyan", (255, 0, 255): "magenta", (255, 255, 0): "yellow", (255, 255, 255): "white",
}


def _rows(sprite):
    return sprite.split("\n") if isinstance(sprite, str) else list(sprite)


def _placements(scene):
    items = list(scene.get("items", []))
    for extra in scene.get("frames") or []:
        items += extra
    return items


def _baked(scene):
    notes = scene.get("notes", {})
    baked = {name for name in scene["sprites"] if "baked by" in str(notes.get(name, ""))}
    baked |= {it["sprite"] for it in _placements(scene) if "baked by" in str(it.get("note", ""))}
    return baked


def scene_stats(path):
    scene = json.loads(Path(path).read_text())
    width, height = scene.get("size", PANEL)
    bundle = compile_scene(scene, width, height, frame_ms=scene.get("frame_ms", 200))
    images = [image.convert("RGB") for image in bundle.to_images()]
    colours = set()
    for image in images:
        colours |= {colour for _, colour in image.getcolors(width * height)}
    first = images[0].load()
    lit = sum(1 for y in range(height) for x in range(width) if first[x, y] != (0, 0, 0))
    sprites = {name: _rows(rows) for name, rows in scene["sprites"].items()}
    baked = _baked(scene)
    stats = {
        "canvas": {"width": width, "height": height, "pixels": width * height,
                   "panels": round(width * height / (PANEL[0] * PANEL[1]), 1)},
        "frames": len(images),
        "duration_ms": sum(bundle.frame_durations_ms),
        "picture": {"lit_pixels": lit, "lit_share": round(lit / (width * height), 3),
                    "colours": sorted(NAMES.get(c, str(c)) for c in colours - {(0, 0, 0)})},
        "scene": {"bytes": Path(path).stat().st_size, "sprites": len(sprites),
                  "placements": len(_placements(scene)),
                  "characters": sum(len(row) for rows in sprites.values() for row in rows)},
    }
    if baked:
        stats["provenance"] = provenance(scene, sprites, baked, first, width, height)
    return stats


def provenance(scene, sprites, baked, first, width, height):
    """Which placement shows each lit pixel of the first frame, sorted into baked and hand-painted."""
    owner = [-1] * (width * height)
    items = scene.get("items", []) + ((scene.get("frames") or [[]])[0])
    for index, item in enumerate(items):
        ax, ay = item.get("at", [0, 0])
        for ry, row in enumerate(sprites[item["sprite"]]):
            y = ay + ry
            if 0 <= y < height:
                for rx, char in enumerate(row):
                    x = ax + rx
                    if char != "." and 0 <= x < width:
                        owner[y * width + x] = index
    shown = Counter()
    for spot, index in enumerate(owner):
        if index >= 0 and first[spot % width, spot // width] != (0, 0, 0):
            shown["baked" if items[index]["sprite"] in baked else "hand"] += 1
    total = sum(shown.values()) or 1
    hand = [name for name in sprites if name not in baked]
    return {
        "lit_share_baked": round(shown["baked"] / total, 3),
        "lit_share_hand": round(shown["hand"] / total, 3),
        "baked_sprites": len(sprites) - len(hand),
        "hand_sprites": len(hand),
        "hand_characters": sum(len(row) for name in hand for row in sprites[name]),
    }


def records_stats(folder):
    """Looks, versions, changes and traces, from the log when there is one, else from the files."""
    stats = {"versions": len(list((folder / "versions").glob("*.json")))}
    log = folder / "log.txt"
    if not log.exists():
        looks = [p for p in (folder / "looks").glob("*.png") if "diff" not in p.name]
        return {**stats, "looks": len(looks), "overviews": sum("overview" in p.name for p in looks)}
    text = log.read_text()
    views = dict(re.findall(r"look (\d+) · ([a-z]+)", text))
    traced = [line for line in text.splitlines() if line.startswith("traced:")]
    return {
        **stats,
        "looks": len(views),
        "looks_by_view": dict(Counter(views.values()).most_common()),
        "scales_px": sorted({int(n) for n in re.findall(r"· (\d+) px", text)}),
        "logged_changes": sum(1 for line in text.splitlines() if line.startswith("- ")),
        "traces": len(traced),
        "traced_pixels": sum(len(re.findall(r"\(\d+, \d+\)", line)) for line in traced),
    }


def _strings(value):
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        return sum(_strings(v) for v in value.values())
    if isinstance(value, list):
        return sum(_strings(v) for v in value)
    return 0


def _when(text):
    found = re.search(r"<timestamp>(.*?) \(UTC([+-]\d+)\)</timestamp>", text)
    if not found:
        return None
    moment = datetime.strptime(found.group(1), "%A, %b %d, %Y, %I:%M %p")
    return moment.replace(tzinfo=timezone(timedelta(hours=int(found.group(2)))))


def session_stats(transcript, start, ended=None):
    """The turns from the user message containing start up to the next user message."""
    entries = [json.loads(line) for line in Path(transcript).read_text().splitlines()]
    tools, pictures, text, arguments = Counter(), [], 0, 0
    began, inside, last_turn = None, False, True
    for entry in entries:
        content = (entry.get("message") or {}).get("content")
        parts = [content] if isinstance(content, str) else content or []
        flat = " ".join(p if isinstance(p, str) else p.get("text", "") for p in parts)
        if entry.get("role") == "user":
            if inside:
                last_turn = False
                break
            if start in flat:
                inside, began = True, _when(flat)
            continue
        if not inside or entry.get("role") != "assistant":
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                text += len(part.get("text", ""))
            elif part.get("type") == "tool_use":
                name, given = part.get("name"), part.get("input") or {}
                tools[name] += 1
                arguments += _strings(given)
                if name in ("Read", "ReadFile") and str(given.get("path", "")).endswith(".png"):
                    pictures.append(given["path"])
    if began is None:
        raise SystemExit(f"no user message in {transcript} contains {start!r}")
    if ended is None and last_turn:
        ended = datetime.fromtimestamp(Path(transcript).stat().st_mtime, tz=began.tzinfo)
    image_tokens = 0
    for picture in pictures:
        if Path(picture).exists():
            with Image.open(picture) as image:
                image_tokens += image.width * image.height // 750
    stats = {
        "started": began.isoformat(),
        "tool_calls": sum(tools.values()),
        "tool_calls_by_tool": dict(tools.most_common()),
        "pictures_read": len(pictures),
        "generated_characters": {"tool_arguments": arguments, "messages_and_reasoning": text},
        "generated_tokens_estimate": (arguments + text) // 4,
        "picture_tokens_estimate": image_tokens,
    }
    if ended is not None:
        stats["ended"] = ended.isoformat(timespec="minutes")
        stats["minutes"] = round((ended - began).total_seconds() / 60)
    return stats


def table(rows):
    head = ("piece", "canvas", "frames", "lit", "colours", "sprites", "placements", "chars", "bytes")
    lines = [head]
    for name, s in rows:
        lines.append((name, f"{s['canvas']['width']}x{s['canvas']['height']}", s["frames"],
                      f"{s['picture']['lit_share']:.0%}", len(s["picture"]["colours"]), s["scene"]["sprites"],
                      s["scene"]["placements"], s["scene"]["characters"], s["scene"]["bytes"]))
    widths = [max(len(str(line[i])) for line in lines) for i in range(len(head))]
    return "\n".join("  ".join(str(cell).ljust(w) for cell, w in zip(line, widths, strict=True)) for line in lines)


def main():
    parser = argparse.ArgumentParser(description="Statistics for agent-drawn compositions.")
    parser.add_argument("scenes", nargs="+", type=Path)
    parser.add_argument("--transcript", type=Path, help="The agent transcript (.jsonl) of the session.")
    parser.add_argument("--session-start", help="Text from the user message that started the session.")
    parser.add_argument("--ended", help="When the session ended, ISO 8601; the transcript's mtime if omitted.")
    parser.add_argument("--write", action="store_true", help="Write stats.json beside a single scene.")
    args = parser.parse_args()
    rows = []
    for path in args.scenes:
        stats = {"stats_version": 1, "piece": path.parent.name if path.name == "scene.json" else path.stem,
                 **scene_stats(path)}
        if (path.parent / "looks").is_dir():
            stats["records"] = records_stats(path.parent)
        rows.append((stats["piece"], stats))
    if args.transcript:
        if len(rows) != 1 or not args.session_start:
            raise SystemExit("--transcript needs exactly one scene and --session-start")
        ended = datetime.fromisoformat(args.ended) if args.ended else None
        rows[0][1]["session"] = session_stats(args.transcript, args.session_start, ended)
    if len(rows) == 1:
        text = json.dumps(rows[0][1], indent=2)
        if args.write:
            (args.scenes[0].parent / "stats.json").write_text(text + "\n")
        print(text)
    else:
        print(table(rows))


if __name__ == "__main__":
    main()
