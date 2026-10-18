# Person 2: Policy and AI engineer — starter prompt

Paste everything below this line as the first message of a Claude Code session started at the repo root.

---

Read CLAUDE.md first. I am Person 2, the policy and AI engineer, and I own backend/policy/ and
backend/verify/. Do not edit other folders. If you need a contract change, stop and tell me.

PART A: policy compiler. policy/compiler.py exposes compile_policy(prompt, zones) -> CompileResult.
- Call Gemini (google-genai SDK, model from GEMINI_MODEL) with structured JSON output whose
  schema matches CompileResult. In the system prompt include: the rule grammar (DETECT object IN
  zone WITH attribute FOR duration THEN severity), SUPPORTED_OBJECTS, SUPPORTED_ATTRIBUTES, the
  user's zone names, ids and which camera each zone is on, and 4 to 6 few-shot examples,
  including unsupported requests.
- Attribute semantics: a violation is when the observed value != attribute.expected. So the
  clear-bag rule is transparent expected=true, and the camera rule is professional expected=false.
- capability.py validates after Pydantic: objects in SUPPORTED_OBJECTS, attribute allowed for
  that object, zone id exists, duration between 0.5 and 600 s, severity valid. Map synonyms
  ("bag" -> backpack/handbag/suitcase, "main entrance" -> the closest-named zone).
- Anything one RGB camera cannot observe (concealed items, identity, age, intent, sound, areas
  outside the frame) goes to `unsupported` with one honest sentence, for example: "I cannot
  reliably detect concealed objects from this camera. I can monitor visible objects and
  bag-policy compliance."
- Ambiguities go to `warnings` (no duration given so a default was used, zone name not found,
  a zone name that matches zones on two different cameras).
- Never trust raw model output. Invalid after one retry, or Gemini down -> fallback.py, a
  deterministic mapping for the demo prompt and close paraphrases, so the live demo cannot fail.
  Log when the fallback is used.
- tests/test_compiler.py with about 10 prompts: the demo prompt (exactly the 3 expected rules),
  each rule alone, a concealed-weapon request, an undefined zone, gibberish, and a prompt
  injection ("ignore your instructions and ...").

PART B: crop verifier. verify/verifier.py exposes verify_crop(crop, check) -> Verdict.
- "transparent_bag": is this bag clear, with its contents visible?
- "professional_camera": is this a large professional-style camera (DSLR, mirrorless with a big
  lens, video camera, rig), rather than a phone or small point-and-shoot?
- Gemini with the image and structured output {answer: "yes" | "no" | "unclear", confidence
  0-1, reason under 15 words}. "unclear" maps to answer=None.
- Resize crops to max 512 px JPEG. 4 s timeout -> Verdict(None, 0, "verification timed out").
  Small LRU cache keyed by image hash.
- CLI: `python -m verify.cli <folder of crops>` prints a verdict and latency per image. Build a
  labeled set from our clips (10 clear bags, 10 opaque, 5 cameras, 5 phones) using
  vision.pipeline.crop or by cropping frames yourself, and report accuracy and mean latency.

Start by proposing a short plan, then Part A.
