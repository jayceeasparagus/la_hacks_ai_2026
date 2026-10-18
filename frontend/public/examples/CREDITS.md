# Example videos

Rendered by `demo/render_ppe_examples.py` from Pexels stock footage (Pexels license: free to use, no
attribution required). Boxes come from Person 1's detector; the hard-hat and hi-vis-vest verdicts are
Gemini's answers on each worker's clearest crop, cached in `demo/ppe_verdicts.json`.

| File | Source |
|---|---|
| construction_site.mp4 / .jpg | https://www.pexels.com/video/back-view-of-workers-walking-in-construction-site-5434220/ |
| warehouse.mp4 / .jpg | https://www.pexels.com/video/men-working-in-a-warehouse-4281236/ |

Labels stay neutral ("not seen", never "violation"): these are real people in stock footage.
