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
}
