"""Minimal preview overlays; model internals stay out of the operator view."""

import cv2
import numpy as np


def annotate(image, zones, tf, states):
    result = image.copy()
    height, width = result.shape[:2]
    for zone in zones:
        if zone.camera_id != tf.camera_id:
            continue
        points = np.array([(round(x * (width - 1)), round(y * (height - 1)))
                           for x, y in zone.polygon], dtype=np.int32)
        overlay = result.copy()
        cv2.fillPoly(overlay, [points], (100, 160, 100))
        cv2.addWeighted(overlay, 0.15, result, 0.85, 0, result)
        cv2.polylines(result, [points], True, (100, 200, 100), 2)
        cv2.putText(result, zone.name, tuple(points[0]), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (200, 255, 200), 1)
    for track in tf.tracks:
        x1, y1, x2, y2 = track.bbox
        cv2.rectangle(result, (round(x1 * width), round(y1 * height)),
                      (round(x2 * width), round(y2 * height)), (0, 200, 240), 2)
    for index, state in enumerate(states):
        text = f'{state.rule_id}: {state.elapsed_seconds:.1f} / {state.duration_seconds:g}s ({state.phase})'
        color = (0, 0, 255) if state.phase == 'alerted' else (0, 220, 240)
        cv2.putText(result, text, (8, height - 12 - index * 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    return result
