# Third-party notices

OpenSign · CoolLED is released under the MIT License (see [LICENSE](LICENSE)). It also includes code adapted from the project below, which is distributed under its own license.

## coolledx-driver

Portions of the CoolLEDX codec, notably the 128-byte chunk layout and the column-major RGB bitplane packing (`_chop_into_chunks` and `_pixel_bitplanes` in `src/opensign/protocol/codecs/coolledx.py`), are adapted from [coolledx-driver](https://github.com/UpDryTwist/coolledx-driver), which is itself derived from CrimsonClyde's led-faceshields work. Protocol facts (opcodes, framing, byte escaping) are re-implemented and cited in [protocol.md](protocol.md).

```text
MIT License

Copyright (c) 2025 Greg Tatham

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
