# Person 1: Vision engineer — starter prompt

Paste everything below this line as the first message of a Claude Code session started at the repo root.

---

Read CLAUDE.md first. I am Person 1, the vision engineer, and I own backend/vision/. Do not edit
other folders. If you need a contract change in backend/app/models.py, stop and tell me.

Goal: a VisionPipeline that turns a webcam or video file into raw frames + TrackFrame objects,
fast enough for a live demo on this laptop.

Build in this order. Test each step on the clips in clips/ before moving on.

1. capture.py: open "webcam:N", "url:<http or rtsp stream from a phone app>" or "clip:<path>"
   with OpenCV, 1280x720 for one camera and 960 px wide when two or more run. For clips, ts comes
   from frame index / file FPS so replays are deterministic, with a --realtime flag to play at
   true speed. Webcam capture runs in its own thread and always serves the newest frame.
2. detector.py: ultralytics YOLO-World (yolov8s-worldv2.pt) with
   set_classes(["person", "backpack", "handbag", "suitcase", "chair", "camera"]).
   Per-class confidence thresholds in one config dict. Auto-select device (cuda, mps, cpu).
3. Tracking: ByteTrack via model.track(persist=True, tracker="bytetrack.yaml"). Stable
   track_ids, class names mapped to our contract.
4. pipeline.py: VisionPipeline(camera) with frames() yielding (frame, TrackFrame), a ring
   buffer of the last 10 s of frames exposed as recent_frames(seconds) for evidence clips, and
   crop(frame, bbox, pad=0.15) returning a padded crop.
5. annotate.py: draw_annotations(frame, zones, tracks, rule_states). Zone polygons (normalized
   coords) as semi-transparent fills with names, boxes with class + track id, and small progress
   labels like "Exit obstruction 3.2 / 5 s". Urgent states in red. Clean and minimal.
6. dump.py: `python -m vision.dump clips/x.mp4` writes clips/x.tracks.jsonl (one TrackFrame per
   line) and clips/x.annotated.mp4. Teammates build the engine from these files without
   running the model.

7. Multiple cameras: each VisionPipeline owns its own YOLO-World model and tracker, because
   ultralytics track(persist=True) keeps tracker state on the model and a shared model would
   mix track ids across cameras. Run two pipelines at once (laptop webcam + a phone or USB
   webcam) in separate threads. A camera that fails to open or drops reports "offline" and
   retries every 2 s without crashing anything.

Checks to run and report back:
- FPS on this laptop for one webcam, for a clip, and per camera with two cameras running.
- For each clip: detection counts per class and the number of unique track ids. The bag in
  exit_bag.mp4 must keep one track id while it sits still; report any ID switches.
- Whether "camera" fires on a large camera and stays quiet on a held-up phone. If it is weak,
  try class prompts like "DSLR camera" and "video camera" and report which works best.

Ask before installing anything beyond ultralytics and opencv-python. Start by proposing a
short plan, then implement step 1.
