# -*- coding: utf-8 -*-

"""Pen to rasterize paths with FreeType."""

__all__ = ['FreeTypePen']

import os
import ctypes
import platform
import subprocess
import collections
import math

import freetype
from freetype.raw import FT_Outline_Get_Bitmap, FT_Outline_Get_BBox, FT_Outline_Get_CBox
from freetype.ft_types import FT_Pos
from freetype.ft_structs import FT_Vector, FT_BBox, FT_Bitmap, FT_Outline
from freetype.ft_enums import FT_OUTLINE_NONE, FT_OUTLINE_EVEN_ODD_FILL, FT_PIXEL_MODE_GRAY
from freetype.ft_errors import FT_Exception

from fontTools.pens.basePen import BasePen
from fontTools.misc.roundTools import otRound

Contour   = collections.namedtuple('Contour', ('points', 'tags'))
LINE      = 0b00000001
CURVE     = 0b00000011
OFFCURVE  = 0b00000010
QCURVE    = 0b00000001
QOFFCURVE = 0b00000000

class FreeTypePen(BasePen):
    """Pen to rasterize paths with FreeType. Requires `freetype-py` module.

    Constructs ``FT_Outline`` from the paths, and renders it within a bitmap
    buffer.

    For ``array()`` and ``show()``, `numpy` and `matplotlib` must be installed.
    For ``image()``, `Pillow` is required. Each module is lazily loaded when the
    corresponding method is called.

    Args:
        glyphSet: a dictionary of drawable glyph objects keyed by name
            used to resolve component references in composite glyphs.

    :Examples:
        If `numpy` and `matplotlib` is available, the following code will
        show the glyph image of `fi` in a new window::

            from fontTools.ttLib import TTFont
            from fontTools.pens.freetypePen import FreeTypePen
            pen = FreeTypePen(None)
            font = TTFont('SourceSansPro-Regular.otf')
            glyph = font.getGlyphSet()['fi']
            glyph.draw(pen)
            width, ascender, descender = glyph.width, font['OS/2'].usWinAscent, -font['OS/2'].usWinDescent
            height = ascender - descender
            pen.show(offset=(0, -descender), width=width, height=height)

        Combining with `uharfbuzz`, you can typeset a chunk of glyphs in a pen::

            import uharfbuzz as hb
            from fontTools.pens.freetypePen import FreeTypePen
            from fontTools.pens.transformPen import TransformPen
            from fontTools.misc.transform import Offset

            en1, en2, ar, ja = 'Typesetting', 'Jeff', 'صف الحروف', 'たいぷせっと'
            for text, font_path, direction, typo_ascender, typo_descender, vhea_ascender, vhea_descender, contain, features in (
                (en1, 'NotoSans-Regular.ttf',       'ltr', 2189, -600, None, None, False, {"kern": True, "liga": True}),
                (en2, 'NotoSans-Regular.ttf',       'ltr', 2189, -600, None, None, True,  {"kern": True, "liga": True}),
                (ar,  'NotoSansArabic-Regular.ttf', 'rtl', 1374, -738, None, None, False, {"kern": True, "liga": True}),
                (ja,  'NotoSansJP-Regular.otf',     'ltr', 880,  -120, 500,  -500, False, {"palt": True, "kern": True}),
                (ja,  'NotoSansJP-Regular.otf',     'ttb', 880,  -120, 500,  -500, False, {"vert": True, "vpal": True, "vkrn": True})
            ):
                blob = hb.Blob.from_file_path(font_path)
                face = hb.Face(blob)
                font = hb.Font(face)
                buf = hb.Buffer()
                buf.direction = direction
                buf.add_str(text)
                buf.guess_segment_properties()
                hb.shape(font, buf, features)

                x, y = 0, 0
                pen = FreeTypePen(None)
                for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
                    gid = info.codepoint
                    transformed = TransformPen(pen, Offset(x + pos.x_offset, y + pos.y_offset))
                    font.draw_glyph_with_pen(gid, transformed)
                    x += pos.x_advance
                    y += pos.y_advance

                offset, width, height = None, None, None
                if direction in ('ltr', 'rtl'):
                    offset = (0, -typo_descender)
                    width  = x
                    height = typo_ascender - typo_descender
                else:
                    offset = (-vhea_descender, -y)
                    width  = vhea_ascender - vhea_descender
                    height = -y
                pen.show(offset=offset, width=width, height=height, contain=contain)

        For Jupyter Notebook, the rendered image will be displayed in a cell if
        you replace ``show()`` with ``image()`` in the examples.
    """

    def __init__(self, glyphSet):
        BasePen.__init__(self, glyphSet)
        self.contours = []

    def outline(self, offset=None, scale=None, evenOdd=False):
        """Converts the current contours to ``FT_Outline``.

        Args:
            offset: A optional tuple of ``(x, y)`` used for translation.
            scale:  A optional tuple of ``(scale_x, scale_y)`` used for scaling.
            evenOdd: Pass ``True`` for even-odd fill instead of non-zero.
        """
        offset = offset or (0, 0)
        scale  = scale  or (1.0, 1.0)
        nContours = len(self.contours)
        n_points   = sum((len(contour.points) for contour in self.contours))
        points = []
        for contour in self.contours:
            for point in contour.points:
                points.append(FT_Vector(FT_Pos(otRound((point[0] + offset[0]) * scale[0] * 64)), FT_Pos(otRound((point[1] + offset[1]) * scale[1] * 64))))
        tags = []
        for contour in self.contours:
            for tag in contour.tags:
                tags.append(tag)
        contours = []
        contours_sum = 0
        for contour in self.contours:
            contours_sum += len(contour.points)
            contours.append(contours_sum - 1)
        flags = FT_OUTLINE_EVEN_ODD_FILL if evenOdd else FT_OUTLINE_NONE
        return FT_Outline(
            (ctypes.c_short)(nContours),
            (ctypes.c_short)(n_points),
            (FT_Vector      * n_points)(*points),
            (ctypes.c_ubyte * n_points)(*tags),
            (ctypes.c_short * nContours)(*contours),
            (ctypes.c_int)(flags)
        )

    def buffer(self, offset=None, width=1000, height=1000, evenOdd=False, scale=None, contain=False):
        """Renders the current contours within a bitmap buffer.

        Args:
            offset: A optional tuple of ``(x, y)`` used for translation.
                Typically ``(0, -descender)`` can be passed so that the glyph
                image would not been clipped.
            width:  Image width of the bitmap in pixels.
            height:  Image height of the bitmap in pixels.
            scale:  A optional tuple of ``(scale_x, scale_y)`` used for scaling.
            evenOdd: Pass ``True`` for even-odd fill instead of non-zero.
            contain: If ``True``, the image size will be automatically expanded
                so that it fits to the bounding box of the paths. Useful for
                rendering glyphs with negative sidebearings without clipping.

        Returns:
            A tuple of ``(buffer, size)``, where ``buffer`` is a ``bytes``
            object of the resulted bitmap and ``size` is a 2-tuple of its
            dimension.
        
        :Example:
            >>> pen = FreeTypePen(None)
            >>> glyph.draw(pen)
            >>> buf, size = pen.buffer(width=500, height=1000)
            >>> type(buf), len(buf), size
            (<class 'bytes'>, 500000, (500, 1000))
        """
        offset_x, offset_y = offset or (0, 0)
        if contain:
            bbox      = self.bbox
            bbox_size = bbox[2] - bbox[0], bbox[3] - bbox[1]
            offset_x  = min(offset_x, bbox[0]) * -1
            width     = max(width,  bbox_size[0])
            offset_y  = min(offset_y, bbox[1]) * -1
            height    = max(height, bbox_size[1])
        scale  = scale or (1.0, 1.0)
        width  = math.ceil(width  * scale[0])
        height = math.ceil(height * scale[1])
        buf = ctypes.create_string_buffer(width * height)
        bitmap = FT_Bitmap(
            (ctypes.c_int)(height),
            (ctypes.c_int)(width),
            (ctypes.c_int)(width),
            (ctypes.POINTER(ctypes.c_ubyte))(buf),
            (ctypes.c_short)(256),
            (ctypes.c_ubyte)(FT_PIXEL_MODE_GRAY),
            (ctypes.c_char)(0),
            (ctypes.c_void_p)(None)
        )
        outline = self.outline(offset=(offset_x, offset_y), evenOdd=evenOdd, scale=scale)
        err = FT_Outline_Get_Bitmap(freetype.get_handle(), ctypes.byref(outline), ctypes.byref(bitmap))
        if err != 0:
            raise FT_Exception(err)
        return buf.raw, (width, height)

    def array(self, offset=None, width=1000, height=1000, evenOdd=False, scale=None, contain=False):
        """Returns the rendered contours as a numpy array. Requires `numpy`.

        Args:
            offset: A optional tuple of ``(x, y)`` used for translation.
                Typically ``(0, -descender)`` can be passed so that the glyph
                image would not been clipped.
            width:  Image width of the bitmap in pixels.
            height:  Image height of the bitmap in pixels.
            scale:  A optional tuple of ``(scale_x, scale_y)`` used for scaling.
            evenOdd: Pass ``True`` for even-odd fill instead of non-zero.
            contain: If ``True``, the image size will be automatically expanded
                so that it fits to the bounding box of the paths. Useful for
                rendering glyphs with negative sidebearings without clipping.

        Returns:
            A ``numpy.ndarray`` object with a shape of ``(height, width)``.
            Each element takes a value in the range of ``[0.0, 1.0]``.
        
        :Example:
            >>> pen = FreeTypePen(None)
            >>> glyph.draw(pen)
            >>> arr = pen.array(width=500, height=1000)
            >>> type(a), a.shape
            (<class 'numpy.ndarray'>, (1000, 500))
        """
        import numpy as np
        buf, size = self.buffer(offset=offset, width=width, height=height, evenOdd=evenOdd, scale=scale, contain=contain)
        return np.frombuffer(buf, 'B').reshape((size[1], size[0])) / 255.0

    def show(self, offset=None, width=1000, height=1000, evenOdd=False, scale=None, contain=False):
        """Plots the rendered contours with `pyplot`. Requires `numpy` and
        `matplotlib`.

        Args:
            offset: A optional tuple of ``(x, y)`` used for translation.
                Typically ``(0, -descender)`` can be passed so that the glyph
                image would not been clipped.
            width:  Image width of the bitmap in pixels.
            height:  Image height of the bitmap in pixels.
            scale:  A optional tuple of ``(scale_x, scale_y)`` used for scaling.
            evenOdd: Pass ``True`` for even-odd fill instead of non-zero.
            contain: If ``True``, the image size will be automatically expanded
                so that it fits to the bounding box of the paths. Useful for
                rendering glyphs with negative sidebearings without clipping.
        
        :Example:
            >>> pen = FreeTypePen(None)
            >>> glyph.draw(pen)
            >>> pen.show(width=500, height=1000)
        """
        from matplotlib import pyplot as plt
        a = self.array(offset=offset, width=width, height=height, evenOdd=evenOdd, scale=scale, contain=contain)
        plt.imshow(a, cmap='gray_r', vmin=0, vmax=1)
        plt.show()

    def image(self, offset=None, width=1000, height=1000, evenOdd=False, scale=None, contain=False):
        """Returns the rendered contours as a PIL image. Requires `Pillow`.
        Can be used to display a glyph image in Jupyter Notebook.

        Args:
            offset: A optional tuple of ``(x, y)`` used for translation.
                Typically ``(0, -descender)`` can be passed so that the glyph
                image would not been clipped.
            width:  Image width of the bitmap in pixels.
            height:  Image height of the bitmap in pixels.
            scale:  A optional tuple of ``(scale_x, scale_y)`` used for scaling.
            evenOdd: Pass ``True`` for even-odd fill instead of non-zero.
            contain: If ``True``, the image size will be automatically expanded
                so that it fits to the bounding box of the paths. Useful for
                rendering glyphs with negative sidebearings without clipping.

        Returns:
            A ``PIL.image`` object. The image is filled in black with alpha
            channel obtained from the rendered bitmap.
        
        :Example:
            >>> pen = FreeTypePen(None)
            >>> glyph.draw(pen)
            >>> img = pen.image(width=500, height=1000)
            >>> type(img), img.size
            (<class 'PIL.Image.Image'>, (500, 1000))
        """
        from PIL import Image
        buf, size = self.buffer(offset=offset, width=width, height=height, evenOdd=evenOdd, scale=scale, contain=contain)
        img = Image.new('L', size, 0)
        img.putalpha(Image.frombuffer('L', size, buf))
        return img

    @property
    def bbox(self):
        """Computes the exact bounding box of an outline.

        Returns:
            A tuple of ``(xMin, yMin, xMax, yMax)``.
        """
        bbox = FT_BBox()
        outline = self.outline()
        FT_Outline_Get_BBox(ctypes.byref(outline), ctypes.byref(bbox))
        return (bbox.xMin / 64.0, bbox.yMin / 64.0, bbox.xMax / 64.0, bbox.yMax / 64.0)

    @property
    def cbox(self):
        """Returns an outline's ‘control box’.

        Returns:
            A tuple of ``(xMin, yMin, xMax, yMax)``.
        """
        cbox = FT_BBox()
        outline = self.outline()
        FT_Outline_Get_CBox(ctypes.byref(outline), ctypes.byref(cbox))
        return (cbox.xMin / 64.0, cbox.yMin / 64.0, cbox.xMax / 64.0, cbox.yMax / 64.0)

    def _moveTo(self, pt):
        contour = Contour([], [])
        self.contours.append(contour)
        contour.points.append(pt)
        contour.tags.append(LINE)

    def _lineTo(self, pt):
        contour = self.contours[-1]
        contour.points.append(pt)
        contour.tags.append(LINE)

    def _curveToOne(self, p1, p2, p3):
        t1, t2, t3 = OFFCURVE, OFFCURVE, CURVE
        contour = self.contours[-1]
        for p, t in ((p1, t1), (p2, t2), (p3, t3)):
            contour.points.append(p)
            contour.tags.append(t)

    def _qCurveToOne(self, p1, p2):
        t1, t2 = QOFFCURVE, QCURVE
        contour = self.contours[-1]
        for p, t in ((p1, t1), (p2, t2)):
            contour.points.append(p)
            contour.tags.append(t)
