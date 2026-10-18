"""Run the hybrid pipeline on clips and save every request that WOULD go to Gemini.

    python -m vision.evidence_run ../clips/pexels/gate_man_ticket.mp4 --zones vision/test_zones.json --out ../clips/gemini_snapshots
    python -m vision.evidence_run --viewer-only --out ../clips/gemini_snapshots      # rebuild index.html

Per clip it writes <out>/<clip>/: zones.jpg, summary.json and one folder per request
(images + request.json). index.html shows them all for an eye test.
"""

import argparse
import base64
import html
import json
import time
from pathlib import Path

import cv2

from vision.annotate import draw_annotations
from vision.evidence import CONTEXT_WIDTH, EvidenceCollector, ExitEvent, PersonEvent
from vision.gemini_request import write_exit_request, write_person_request
from vision.pipeline import VisionPipeline
from vision.zones import load_zones

HIGHLIGHT = (0, 255, 255)


def _shrink(img):
    if img.shape[1] <= CONTEXT_WIDTH:
        return img
    return cv2.resize(img, (CONTEXT_WIDTH, int(img.shape[0] * CONTEXT_WIDTH / img.shape[1])), interpolation=cv2.INTER_AREA)


def run_clip(path: Path, zones_file: Path | None, out_root: Path, imgsz: int) -> dict:
    name = path.stem
    zones = load_zones(zones_file, name)
    zone_dicts = [{"name": f"{z.name} ({z.kind})", "polygon": z.polygon} for z in zones]

    def draw_context(image, tf, bbox):
        view = draw_annotations(image, zone_dicts, tf.tracks)
        h, w = view.shape[:2]
        cv2.rectangle(view, (int(bbox[0] * w), int(bbox[1] * h)), (int(bbox[2] * w), int(bbox[3] * h)), HIGHLIGHT, 4)
        return _shrink(view)

    out = out_root / name
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*/request.json"):  # fresh run
        old.unlink()
    pipe = VisionPipeline(name, f"clip:{path}", imgsz=imgsz)
    coll = EvidenceCollector(zones, draw_context=draw_context)
    requests, frames, start, last_tf = [], 0, time.monotonic(), None

    def emit(events):
        for ev in events:
            rid = f"{len(requests) + 1:03d}_{'person' if isinstance(ev, PersonEvent) else 'exit'}_t{ev.visit.track_id}"
            if isinstance(ev, PersonEvent):
                requests.append(write_person_request(ev, out, name, name, rid))
            elif isinstance(ev, ExitEvent):
                requests.append(write_exit_request(ev, out, name, name, rid))

    for image, tf in pipe.frames():
        if frames == 0:
            cv2.imwrite(str(out / "zones.jpg"), _shrink(draw_annotations(image, zone_dicts)), [cv2.IMWRITE_JPEG_QUALITY, 80])
        frames += 1
        last_tf = tf
        emit(coll.update(tf, image, pipe.latest_full))
    emit(coll.finish())
    pipe.stop()

    summary = {
        "clip": name, "frames": frames, "clip_seconds": round(last_tf.ts, 1) if last_tf else 0,
        "process_seconds": round(time.monotonic() - start, 1),
        "zones": [{"name": z.name, "kind": z.kind, "polygon": z.polygon, "note": z.note} for z in zones],
        "requests": len(requests),
        "person_requests": sum(r["kind"] == "person_attributes" for r in requests),
        "exit_requests": sum(r["kind"] == "exit_confirmation" for r in requests),
        "skipped": [s.__dict__ for s in coll.skipped],
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{name}: {frames} frames, {summary['person_requests']} person + {summary['exit_requests']} exit requests, "
          f"{len(coll.skipped)} skipped, {summary['process_seconds']} s", flush=True)
    return summary


# ---- viewer ----------------------------------------------------------------------

CSS = """
:root { color-scheme: dark; }
body { background:#14161a; color:#e6e6e6; font:14px/1.45 system-ui, sans-serif; margin:0; padding:16px; }
h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:17px; margin:28px 0 6px; border-top:1px solid #333; padding-top:16px; }
.muted { color:#9aa0a6; } table { border-collapse:collapse; margin:10px 0; } td,th { padding:4px 10px; border-bottom:1px solid #2a2d33; text-align:left; }
.cards { display:flex; flex-wrap:wrap; gap:14px; } .card { background:#1d2026; border:1px solid #2c3038; border-radius:8px; padding:10px; max-width:100%; }
.card.exit { border-color:#7a2d2d; } .imgs { display:flex; gap:8px; align-items:flex-end; flex-wrap:wrap; }
.imgs figure { margin:0; } .imgs img { height:240px; border-radius:4px; display:block; } .imgs img.small { height:130px; }
figcaption { font-size:11px; color:#9aa0a6; max-width:260px; } .tag { display:inline-block; padding:1px 7px; border-radius:10px; background:#2c3038; font-size:12px; margin-right:4px; }
.tag.exit { background:#7a2d2d; } details { margin-top:6px; } pre { white-space:pre-wrap; background:#111316; padding:8px; border-radius:6px; font-size:12px; max-width:760px; }
.zones img { max-width:min(640px, 100%); max-height:340px; border-radius:6px; } a { color:#8ab4f8; }
"""


def build_viewer(out_root: Path, portable: bool = False) -> Path:
    """index.html links the image files next to it. portable=True writes portable.html with
    downscaled images embedded, a single file small enough to send around (preview only)."""
    clips = sorted(p.parent for p in out_root.glob("*/summary.json"))

    def src(rel: str, max_h: int) -> str:
        if not portable:
            return rel
        img = cv2.imread(str(out_root / rel))
        if img is None:
            return ""
        if img.shape[0] > max_h:
            img = cv2.resize(img, (int(img.shape[1] * max_h / img.shape[0]), max_h), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 72])
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()

    def fig(rel: str, max_h: int, css: str, caption: str) -> str:
        image = f"<img{css} src='{src(rel, max_h)}' loading='lazy'>"
        linked = image if portable else f"<a href='{rel}'>{image}</a>"
        return f"<figure>{linked}<figcaption>{caption}</figcaption></figure>"

    total_req = total_skip = 0
    rows, sections = [], []
    for clip_dir in clips:
        s = json.loads((clip_dir / "summary.json").read_text(encoding="utf-8"))
        reqs = sorted((json.loads(p.read_text(encoding="utf-8")) for p in clip_dir.glob("*/request.json")),
                      key=lambda r: r["request_id"])
        total_req += len(reqs)
        total_skip += len(s["skipped"])
        c = html.escape(s["clip"])
        rows.append(f"<tr><td><a href='#{c}'>{c}</a></td><td>{s['clip_seconds']} s</td><td>{s['person_requests']}</td>"
                    f"<td>{s['exit_requests']}</td><td>{len(s['skipped'])}</td></tr>")
        zone_text = "; ".join(f"<b>{html.escape(z['name'])}</b> ({z['kind']}){' – ' + html.escape(z['note']) if z['note'] else ''}"
                              for z in s["zones"])
        cards = []
        for r in reqs:
            rid = r["request_id"]
            figs = []
            for im in r["images"]:
                small = " class='small'" if im["role"].startswith("close-up") else ""
                extra = []
                for k in ("height_px", "width_px", "sharpness", "conf", "score"):
                    if k in im:
                        extra.append(f"{k}={im[k]}")
                if im.get("cut_off"):
                    extra.append("CUT OFF")
                figs.append(fig(f"{c}/{rid}/{im['file']}", 260 if not small else 160, small,
                                f"{html.escape(im['role'])} · {im['width']}×{im['height']}<br>{' '.join(extra)}"))
            figs.append(fig(f"{c}/{rid}/context.jpg", 220, " class='small'", "context (yellow = this track)"))
            v = r["visit"]
            if r["kind"] == "person_attributes":
                head = (f"<span class='tag'>person #{r['track_id']}</span><span class='tag'>{r['trigger']}</span>"
                        f"<span class='muted'>{v['seconds']} s in {html.escape(r['zone'])}, {v['frames']} frames"
                        f"{' · detector saw: ' + ', '.join(r['detector_saw_carrying']) if r['detector_saw_carrying'] else ''}</span>")
                cls = "card"
            else:
                head = (f"<span class='tag exit'>EXIT CONFIRM · {html.escape(r['detector_label'])} #{r['track_id']}</span>"
                        f"<span class='muted'>{v['seconds_unattended']} s unattended in {html.escape(r['zone'])}</span>")
                cls = "card exit"
            cards.append(f"<div class='{cls}'><div>{head}</div><div class='imgs'>{''.join(figs)}</div>"
                         f"<details><summary>prompt sent with these images</summary><pre>{html.escape(r['prompt'])}</pre></details></div>")
        skipped = "".join(f"<li>#{k['track_id']} in {html.escape(k['zone'])}: {html.escape(k['reason'])}</li>" for k in s["skipped"])
        sections.append(
            f"<h2 id='{c}'>{c} <span class='muted'>· {s['clip_seconds']} s · {len(reqs)} request(s)</span></h2>"
            f"<div class='zones'><p class='muted'>Zones: {zone_text}</p><img src='{src(f"{c}/zones.jpg", 340)}' loading='lazy'></div>"
            f"<div class='cards'>{''.join(cards) or '<p class=muted>No requests.</p>'}</div>"
            f"<details><summary>{len(s['skipped'])} visit(s) not sent, and why</summary><ul>{skipped}</ul></details>")
    page = (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Gemini Request Snapshots</title><style>{CSS}</style></head><body>"
            f"<h1>What would be sent to Gemini</h1>"
            f"<p class='muted'>No calls were made. Each card is one request: the images Gemini would receive, plus the prompt. "
            f"Person requests = one per person per visit to an entrance zone. Exit confirms = an object sat in an exit zone "
            f"for 5 s. {total_req} requests, {total_skip} visits skipped, across {len(clips)} clips. "
            f"{'Images are downscaled previews; full-size files are in clips/gemini_snapshots.' if portable else 'Click any image for full size.'}</p>"
            f"<table><tr><th>clip</th><th>length</th><th>person</th><th>exit</th><th>skipped</th></tr>{''.join(rows)}</table>"
            f"{''.join(sections)}</body></html>")
    index = out_root / ("portable.html" if portable else "index.html")
    index.write_text(page, encoding="utf-8")
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description="Save the Gemini requests the hybrid pipeline would make.")
    parser.add_argument("clips", nargs="*")
    parser.add_argument("--zones", type=Path, default=Path(__file__).parent / "test_zones.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--viewer-only", action="store_true")
    args = parser.parse_args()
    for clip in args.clips:
        run_clip(Path(clip.removeprefix("clip:")), args.zones, args.out, args.imgsz)
    print(f"viewer: {build_viewer(args.out)}")
    portable = build_viewer(args.out, portable=True)
    print(f"portable: {portable} ({portable.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
