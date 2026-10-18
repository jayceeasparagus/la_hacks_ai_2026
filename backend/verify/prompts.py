"""One yes/no visual question per check. answer "yes" maps to Verdict.answer=True."""

QUESTIONS = {
    "transparent_bag": """\
This is a cropped frame from a venue entrance camera. Look at the main bag in the image.
Is it a clear (transparent) bag, meaning you can see its contents or the background through it?
- Answer "yes" for clear plastic, PVC or vinyl bags, including tinted or frosted-but-see-through ones.
- Answer "no" for fabric, leather, canvas, solid plastic, or any bag you cannot see through.
  A small clear window on an otherwise opaque bag is "no".
- Answer "unclear" if there is no bag, it is mostly hidden, or the image is too blurry or dark.
Give a confidence from 0 to 1 and a short reason.""",
    "professional_camera": """\
This is a cropped frame from a venue camera. Look at the main device in the image.
Is it a large, professional-style camera?
- Answer "yes" for DSLRs, mirrorless cameras with a large or long lens, camcorders, cinema or
  broadcast video cameras, or any camera on a rig, gimbal or shoulder mount.
- Answer "no" for phones, tablets, small point-and-shoot cameras, action cameras like GoPros,
  binoculars, or anything that is not a camera.
- Answer "unclear" if there is no device, it is mostly hidden, or the image is too blurry or dark.
Give a confidence from 0 to 1 and a short reason.""",
    "hard_hat": """\
This is a cropped frame from a construction-site camera. Look at the main person in the image.
Is this person wearing a hard hat (a rigid safety helmet) on their head?
- Answer "yes" if a hard hat or rigid safety helmet is on their head.
- Answer "no" for a bare head, a baseball cap, beanie or hood, or a hard hat that is held in the
  hand, hanging from a belt or sitting nearby rather than worn.
- Answer "unclear" if there is no person, their head is cut off or hidden, or the image is too blurry or dark.
Give a confidence from 0 to 1 and a short reason.""",
    "safety_vest": """\
This is a cropped frame from a construction-site camera. Look at the main person in the image.
Is this person wearing a high-visibility safety vest or jacket (fluorescent yellow, orange or lime,
usually with reflective stripes) on their torso?
- Answer "yes" for a hi-vis vest or hi-vis jacket that is being worn.
- Answer "no" for ordinary clothing, including bright clothing without reflective strips, or a vest
  that is carried rather than worn.
- Answer "unclear" if there is no person, their torso is hidden, or the image is too blurry or dark.
Give a confidence from 0 to 1 and a short reason.""",
    # Stretch goal: only used once the contracts support a lying_down attribute.
    "person_down": """\
This is a cropped frame from a venue camera. Look at the main person in the image.
Is this person lying on the floor or ground, as if they fell or collapsed?
- Answer "yes" if their body is lying flat or slumped on the floor or ground.
- Answer "no" if they are standing, walking, sitting on a chair or bench, kneeling, crouching,
  bending over, or lying on a bed, couch or sun lounger.
- Answer "unclear" if there is no person, they are mostly hidden, or the image is too blurry or dark.
Give a confidence from 0 to 1 and a short reason.""",
}

# Which check verifies which Rule attribute. The engine verifies a rule's crop with
# CHECK_FOR_ATTRIBUTE[rule.attribute.name].
CHECK_FOR_ATTRIBUTE = {
    "transparent": "transparent_bag",
    "professional": "professional_camera",
    "hard_hat": "hard_hat",
    "safety_vest": "safety_vest",
    "lying_down": "person_down",
}
