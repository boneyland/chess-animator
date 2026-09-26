"""
manim_fixes.py

Local patch for a manim bug, applied on import. Delete this file and its
imports once the fix is in a manim release.

https://github.com/ManimCommunity/manim/issues/5035
SVGMobject draws shapes with stroke="none" with an opaque white stroke
whenever a stroke width applies to them.  svgelements parses "none" as a
Color with no value, set_style ignores None, and the default stroke (white,
opaque) stays.  In manim-chess this puts a white outline round the black
knight's mane stripe, so the stripe covers the knight's black edge.
"""

from manim import SVGMobject

_apply_style_to_mobject = SVGMobject.apply_style_to_mobject


def _apply_style_hiding_stroke_none(mob, shape):
    mob = _apply_style_to_mobject(mob, shape)
    # Width rather than opacity: Text is an SVGMobject whose glyphs have
    # stroke="none", and Text(...).set_stroke(BLACK, 2) must still show.
    if shape.stroke is None or shape.stroke.value is None:
        mob.set_stroke(width=0)
    return mob


SVGMobject.apply_style_to_mobject = staticmethod(_apply_style_hiding_stroke_none)
