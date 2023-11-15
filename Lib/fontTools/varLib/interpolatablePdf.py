from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import ControlBoundsPen
from fontTools.pens.cairoPen import CairoPen
import cairo
import math


class InterpolatablePdf:
    width = 640
    height = 480
    pad = 16
    line_height = 36

    head_color = (0.3, 0.3, 0.3)
    label_color = (0.2, 0.2, 0.2)
    border_color = (0.9, 0.9, 0.9)
    border_width = 1
    fill_color = (0.8, 0.8, 0.8)
    stroke_color = (0.1, 0.1, 0.1)
    stroke_width = 2

    def __init__(self, outfile, glyphsets, names=None, **kwargs):
        self.outfile = outfile
        self.glyphsets = glyphsets
        self.names = names or [repr(g) for g in glyphsets]

        for k, v in kwargs.items():
            if not hasattr(self, k):
                raise TypeError("Unknown keyword argument: %s" % k)
            setattr(self, k, v)

    def __enter__(self):
        self.surface = cairo.PDFSurface(self.outfile, self.width, self.height)
        return self

    def __exit__(self, type, value, traceback):
        self.surface.finish()

    def add_problems(self, problems):
        for glyph, glyph_problems in problems.items():
            for p in glyph_problems:
                self.add_problem(glyph, p)

    def add_problem(self, glyphname, p):
        master_keys = ("master",) if "master" in p else ("master_1", "master_2")
        master_indices = [self.names.index(p[k]) for k in master_keys]

        total_width = self.width + 2 * self.pad
        total_height = (
            self.pad
            + self.line_height
            + self.pad
            + len(master_indices) * (self.height + self.pad * 2 + self.line_height)
            + self.pad
        )

        self.surface.set_size(total_width, total_height)

        x = self.pad
        y = self.pad

        self.draw_label(glyphname, y=y, color=self.head_color, align=0)
        self.draw_label(p["type"], y=y, color=self.head_color, align=1)
        y += self.line_height + self.pad

        for master_idx in master_indices:
            glyphset = self.glyphsets[master_idx]
            name = self.names[master_idx]

            self.draw_label(name, y=y, color=self.label_color, align=0.5)
            y += self.line_height + self.pad

            self.draw_glyph(glyphset, glyphname, x=x, y=y)

            y += self.height + self.pad

        self.surface.show_page()

    def draw_label(self, label, *, y=0, color=(0, 0, 0), align=0):
        cr = cairo.Context(self.surface)
        cr.select_font_face("@cairo", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        cr.set_font_size(self.line_height)
        font_extents = cr.font_extents()
        font_size = self.line_height * self.line_height / font_extents[2]
        cr.set_font_size(font_size)
        font_extents = cr.font_extents()

        cr.set_source_rgb(*color)

        extents = cr.text_extents(label)
        if extents.width > self.width:
            # Shrink
            font_size *= self.width / extents.width
            cr.set_font_size(font_size)
            font_extents = cr.font_extents()
            extents = cr.text_extents(label)

        # Center
        label_x = (self.width - extents.width) * align + self.pad
        label_y = y + font_extents[0]
        cr.move_to(label_x, label_y)
        cr.show_text(label)

    def draw_glyph(self, glyphset, glyphname, *, x=0, y=0):
        glyph = glyphset[glyphname]

        boundsPen = ControlBoundsPen(glyphset)
        glyph.draw(boundsPen)

        glyph_width = boundsPen.bounds[2] - boundsPen.bounds[0]
        glyph_height = boundsPen.bounds[3] - boundsPen.bounds[1]

        scale = min(self.width / glyph_width, self.height / glyph_height)

        cr = cairo.Context(self.surface)
        cr.translate(x, y)
        # Center
        cr.translate(
            (self.width - glyph_width * scale) / 2,
            (self.height - glyph_height * scale) / 2,
        )
        cr.scale(scale, -scale)
        cr.translate(-boundsPen.bounds[0], -boundsPen.bounds[3])

        if self.border_color:
            cr.set_source_rgb(*self.border_color)
            cr.rectangle(
                boundsPen.bounds[0], boundsPen.bounds[1], glyph_width, glyph_height
            )
            cr.set_line_width(self.border_width / scale)
            cr.stroke()

        if self.fill_color:
            pen = CairoPen(glyphset, cr)
            glyph.draw(pen)
            cr.set_source_rgb(*self.fill_color)
            cr.fill()

        if self.stroke_color:
            pen = CairoPen(glyphset, cr)
            glyph.draw(pen)
            cr.set_source_rgb(*self.stroke_color)
            cr.set_line_width(self.stroke_width / scale)
            cr.stroke()
