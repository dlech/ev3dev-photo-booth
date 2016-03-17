#!/usr/bin/env python3

# ev3-photobooth.py
#
# A simple program for taking photos with a webcam on LEGO MINDSTORMS EV3 (running ev3dev).

# The MIT License (MIT)
#
# Copyright (c) 2016 David Lechner <david@lechnology.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import evdev
from evdev import InputDevice, ecodes
from collections import namedtuple
from ctypes import Structure, c_char, c_short, c_ushort, c_uint, c_ulong, c_uint16, c_uint32
from enum import Enum
from fcntl import ioctl
from subprocess import Popen
from PIL import Image, ImageDraw, ImageFont, ImageMath
from selectors import DefaultSelector, EVENT_READ
from sys import stderr
from errno import *
from struct import pack, unpack
import time
import contextlib

class Framebuffer(object):

    # ioctls
    _FBIOGET_VSCREENINFO = 0x4600
    _FBIOGET_FSCREENINFO = 0x4602
    _FBIOGET_CON2FBMAP = 0x460F

    class Type(Enum):
        PACKED_PIXELS = 0                   # Packed Pixels
        PLANES = 1                          # Non interleaved planes
        INTERLEAVED_PLANES = 2              # Interleaved planes
        TEXT = 3                            # Text/attributes
        VGA_PLANES = 4                      # EGA/VGA planes
        FOURCC = 5                          # Type identified by a V4L2 FOURCC

    class Visual(Enum):
        MONO01 = 0                          # Monochrome 1=Black 0=White
        MONO10 = 1                          # Monochrome 1=White 0=Black
        TRUECOLOR = 2                       # True color
        PSEUDOCOLOR = 3                     # Pseudo color (like atari)
        DIRECTCOLOR = 4                     # Direct color
        STATIC_PSEUDOCOLOR = 5              # Pseudo color readonly
        FOURCC = 6                          # Visual identified by a V4L2 FOURCC

    class _FixedScreenInfo(Structure):
        _fields_ = [
            ('id', c_char * 16),            # identification string eg "TT Builtin"
            ('smem_start', c_ulong),        # Start of frame buffer mem (physical address)
            ('smem_len', c_uint32),		    # Length of frame buffer mem
            ('type', c_uint32),             # see FB_TYPE_*
            ('type_aux', c_uint32),         # Interleave for interleaved Planes
            ('visual', c_uint32),           # see FB_VISUAL_*
            ('xpanstep', c_uint16),		    # zero if no hardware panning
            ('ypanstep', c_uint16),		    # zero if no hardware panning
            ('ywrapstep', c_uint16),        # zero if no hardware ywrap
            ('line_length', c_uint32),      # length of a line in bytes
            ('mmio_start', c_ulong),        # Start of Memory Mapped I/O (physical address)
            ('mmio_len', c_uint32),         # Length of Memory Mapped I/O
            ('accel', c_uint32),            # Indicate to driver which specific chip/card we have
            ('capabilities', c_uint16),     # see FB_CAP_*
            ('reserved', c_uint16 * 2),     # Reserved for future compatibility
        ]

    class _VariableScreenInfo(Structure):

        class _Bitfield(Structure):
            _fields_ = [
                ('offset', c_uint32),       # beginning of bitfield
                ('length', c_uint32),       # length of bitfield
                ('msb_right', c_uint32),    # != 0 : Most significant bit is right
            ]

        _fields_ = [
            ('xres', c_uint32),             # visible resolution
            ('yres', c_uint32),
            ('xres_virtual', c_uint32),     # virtual resolution
            ('yres_virtual', c_uint32),
            ('xoffset', c_uint32),          # offset from virtual to visible
            ('yoffset', c_uint32),          # resolution
            ('bits_per_pixel', c_uint32),   # guess what
            ('grayscale', c_uint32),        # 0 = color, 1 = grayscale, >1 = FOURCC
            ('red', _Bitfield),             # bitfield in fb mem if true color,
            ('green', _Bitfield),           # else only length is significant
            ('blue', _Bitfield),
            ('transp', _Bitfield),          # transparency
            ('nonstd', c_uint32),           # != 0 Non standard pixel format
            ('activate', c_uint32),         # see FB_ACTIVATE_*
            ('height', c_uint32),           # height of picture in mm
            ('width', c_uint32),            # width of picture in mm
            ('accel_flags', c_uint32),      # (OBSOLETE) see fb_info.flags
            # Timing: All values, in pixclocks, except pixclock (of course)
            ('pixclock', c_uint32),         # pixel clock in ps (pico seconds)
            ('left_margin', c_uint32),      # time from sync to picture
            ('right_margin', c_uint32),     # time from picture to sync
            ('upper_margin', c_uint32),     # time from sync to picture
            ('lower_margin', c_uint32),
            ('hsync_len', c_uint32),        # length of horizontal sync
            ('vsync_len', c_uint32),        # length of vertical sync
            ('sync', c_uint32),             # see FB_SYNC_*
            ('vmode', c_uint32),            # see FB_VMODE_*
            ('rotate', c_uint32),           # angle we rotate counter clockwise
            ('colorspace', c_uint32),       # colorspace for FOURCC-based modes
            ('reserved', c_uint32 * 4),     # Reserved for future compatibility
        ]

    class _Console2FramebufferMap(Structure):
        _fields_ = [
            ('console', c_uint32),
            ('framebuffer', c_uint32),
        ]

    def __init__(self, device='/dev/fb0'):
        self._fd = open(device, mode='r+b', buffering=0)
        self._fixed_info = self._FixedScreenInfo()
        ioctl(self._fd, self._FBIOGET_FSCREENINFO, self._fixed_info)
        self._variable_info = self._VariableScreenInfo()
        ioctl(self._fd, self._FBIOGET_VSCREENINFO, self._variable_info)

    def close(self):
        self._fd.close()

    def clear(self):
        self._fd.seek(0)
        self._fd.write(b'\0' * self._fixed_info.smem_len)

    def write_raw(self, data):
        self._fd.seek(0)
        self._fd.write(data)

    @staticmethod
    def get_fb_for_console(console):
        with open('/dev/fb0', mode='r+b') as fd:
            m = Framebuffer._Console2FramebufferMap()
            m.console = console
            ioctl(fd, Framebuffer._FBIOGET_CON2FBMAP, m)
            return Framebuffer('/dev/fb{}'.format(m.framebuffer))

    @property
    def type(self):
        return self.Type(self._fixed_info.type)

    @property
    def visual(self):
        return self.Visual(self._fixed_info.visual)

    @property
    def line_length(self):
        return self._fixed_info.line_length

    @property
    def resolution(self):
        """Visible resolution"""
        Resolution = namedtuple('Resolution', 'x y')
        return Resolution(self._variable_info.xres, self._variable_info.yres)

    @property
    def bits_per_pixel(self):
        return self._variable_info.bits_per_pixel

    @property
    def grayscale(self):
        return self._variable_info.grayscale

    @property
    def size(self):
        """Size of picture in mm"""
        Size = namedtuple('Size', 'width height')
        return Size(self._variable_info.width, self._variable_info.height)


class VirtualTerminal(object):

    # ioctls
    _VT_OPENQRY = 0x5600                # find next available vt
    _VT_GETMODE = 0x5601                # get mode of active vt
    _VT_SETMODE = 0x5602                # set mode of active vt
    _VT_GETSTATE = 0x5603               # get global vt state info
    _VT_SENDSIG = 0x5604                # signal to send to bitmask of vts
    _VT_RELDISP = 0x5605                # release display
    _VT_ACTIVATE = 0x5606               # make vt active
    _VT_WAITACTIVE = 0x5607             # wait for vt active
    _VT_DISALLOCATE = 0x5608            # free memory associated to vt
    _VT_SETACTIVATE = 0x560F            # Activate and set the mode of a console
    _KDSETMODE = 0x4B3A                 # set text/graphics mode

    class _VtMode(Structure):
        _fields_ = [
            ('mode', c_char),           # vt mode
            ('waitv', c_char),          # if set, hang on writes if not active
            ('relsig', c_short),        # signal to raise on release request
            ('acqsig', c_short),        # signal to raise on acquisition
            ('frsig', c_short),         # unused (set to 0)
        ]

    class VtMode(Enum):
        AUTO = 0
        PROCESS = 1
        ACKACQ = 2

    class _VtState(Structure):
        _fields_ = [
            ('v_active', c_ushort),     # active vt
            ('v_signal', c_ushort),     # signal to send
            ('v_state', c_ushort),      # vt bitmask
        ]

    class KdMode(Enum):
        TEXT = 0x00
        GRAPHICS = 0x01
        TEXT0 = 0x02                    # obsolete
        TEXT1 = 0x03                    # obsolete

    def __init__(self):
        self._fd = open('/dev/tty', 'r')

    def close(self):
        self._fd.close()

    def get_next_available(self):
        n = c_uint()
        ioctl(self._fd, self._VT_OPENQRY, n)
        return n.value

    def activate(self, num):
        ioctl(self._fd, self._VT_ACTIVATE, num)
        ioctl(self._fd, self._VT_WAITACTIVE, num)

    def get_active(self):
        state = VirtualTerminal._VtState()
        ioctl(self._fd, self._VT_GETSTATE, state)
        return state.v_active

    def set_graphics_mode(self):
        ioctl(self._fd, self._KDSETMODE, self.KdMode.GRAPHICS.value)

    def set_text_mode(self):
        ioctl(self._fd, self._KDSETMODE, self.KdMode.TEXT.value)


class Main(object):
    def __init__(self, fb):
        assert isinstance(fb, Framebuffer)
        self._fb = fb

        # get all input devices
        devices = [InputDevice(fn) for fn in evdev.list_devices()]
        # filter out non key devices
        for device in devices.copy():
            cap = device.capabilities()
            if ecodes.EV_KEY not in cap:
                devices.remove(device)
                continue

        self._selector = DefaultSelector()
        # This works because InputDevice has a `fileno()` method.
        for device in devices:
            self._selector.register(device, EVENT_READ)

    def _color565(self, r, g, b):
        """Convert red, green, blue components to a 16-bit 565 RGB value. Components
        should be values 0 to 255.
        """
        return (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3))

    def _img_to_rgb565_bytes(self):
        pixels = [self._color565(r, g, b) for (r, g, b) in self._img.getdata()]
        return pack('H' * len(pixels), *pixels)

    def _write_image(self, img):
        if (1 == self._fb.bits_per_pixel):
            image_bytes = img.tobytes("raw", "1;IR", self._fb.line_length)
        else:
            self._img = img
            image_bytes = self._img_to_rgb565_bytes()
        self._fb.write_raw(image_bytes)

    def _do_countdown(self):
        if (1 == self._fb.bits_per_pixel):
            img = Image.new("1", self._fb.resolution, 1)
        else:
            img = Image.new("RGB", self._fb.resolution, 'black')

        fnt = ImageFont.truetype(font="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=96)
        d = ImageDraw.Draw(img)
        for i in range(3, 0, -1):
            # clear the image
            d.rectangle(((0, 0), self._fb.resolution), fill=1)
            # draw the text
            text_width, text_height = d.textsize(str(i), font=fnt)
            x = (self._fb.resolution.x - text_width) / 2
            y = (self._fb.resolution.y - text_height) / 2
            d.text((x, y), str(i), font=fnt)
            self._write_image(img)
            # give some time to read
            time.sleep(1.25)

    def _draw_text(self, text, size):
        if (1 == self._fb.bits_per_pixel):
            img = Image.new("1", self._fb.resolution, 1)
        else:
            img = Image.new("RGB", self._fb.resolution, 'black')
        fnt = ImageFont.truetype(font="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=size)
        d = ImageDraw.Draw(img)
        text_width, text_height = d.textsize(text, font=fnt)
        x = (self._fb.resolution.x - text_width) / 2
        y = (self._fb.resolution.y - text_height) / 2
        d.text((x, y), text, font=fnt)
        self._write_image(img)

    def _take_picture(self):
        args = 'fswebcam --quiet --no-banner'
        args += ' --scale {0}x{1}'.format(self._fb.resolution.x, self._fb.resolution.y)
        if self._fb.grayscale or self._fb.bits_per_pixel == 1:
            args += ' --greyscale'
        args += ' --png --save {0}'.format(self._filename)
        fswebcam = Popen(args, shell=True)
        fswebcam.wait()

    def _show_picture(self):
        if (1 == self._fb.bits_per_pixel):
            self._write_image(ImageMath.eval('convert(img, "1")', img=Image.open(self._filename)))
        else:
            self._write_image(img=Image.open(self._filename))

    def run(self):
        self._draw_text('Ready!', 36)
        # TODO: listen for keypresses on a background thread, otherwise they pile up while taking a picture.
        while True:
            for key, mask in self._selector.select():
                device = key.fileobj
                for event in device.read():
                    if event.type != ecodes.EV_KEY:
                        # ignore non-key events
                        continue
                    if not event.value:
                        # ignore key up events
                        continue
                    if event.code in [ecodes.KEY_ENTER, ecodes.KEY_CAMERA]:
                        # enter button or camera button takes a picture
                        self._do_countdown()
                        self._draw_text('Cheese!', 36)
                        self._filename = 'raw-{0}.png'.format(time.strftime("%Y%m%d-%H%M%S"))
                        self._take_picture()
                        self._draw_text('Please wait...', 24)
                        self._show_picture()
                    elif event.code == ecodes.KEY_BACKSPACE:
                        # back button to exit as usual.
                        exit(0)


if __name__ == '__main__':
    try:
        # VirtualTerminal() will fail with ENOTTY if run remotely, e.g. via ssh
        with contextlib.closing(VirtualTerminal()) as vt:
            vt.set_graphics_mode()
            try:
                with contextlib.closing(Framebuffer.get_fb_for_console(vt.get_active())) as fb:
                    main = Main(fb)
                    main.run()
            finally:
                vt.set_text_mode()
    except OSError as e:
        if e.errno == ENOTTY:
            print('Must run this program on a virtual terminal.', file=stderr)
            print('Hint: use `chvt` and `conspy` to remotely control virtual terminals.', file=stderr)
            exit(1)
        # other errors are unexpected
        raise e

