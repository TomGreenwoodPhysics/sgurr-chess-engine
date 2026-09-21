#!/usr/bin/env python3
"""Repack bullet's quantised.bin into Sgurr's .nnue format.

bullet writes each weight column-major, little-endian, in save_format order.
For l0 (shape HL x 768) column-major is feature-major, which is the order
sgurr_cpp/nnue.cpp already expects, so this is a header prepend and a slice --
no transpose.

Layout out:
    "RUKN" | u32 version,input,hl,qa,qb,scale | i16 ft_w[input*hl]
           | i16 ft_b[hl] | i16 out_w[2*hl] | i32 out_bias

Usage: export.py <quantised.bin> <out.nnue> [--hl 1024]
"""
import argparse, pathlib, struct, sys

QA, QB, SCALE, INPUT = 255, 64, 400, 768


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("quantised")
    ap.add_argument("out")
    ap.add_argument("--hl", type=int, default=1024)
    a = ap.parse_args()

    hl = a.hl
    raw = pathlib.Path(a.quantised).read_bytes()

    n_ftw, n_ftb, n_ow = INPUT * hl, hl, 2 * hl
    need = (n_ftw + n_ftb + n_ow) * 2 + 2          # l1b is i16 in save_format
    if len(raw) < need:
        print(f"quantised.bin is {len(raw)} bytes, need >= {need} for hl={hl}",
              file=sys.stderr)
        return 1
    # bullet pads to a multiple of 64 bytes; trailing bytes are padding.

    o = 0
    ft_w = raw[o:o + n_ftw * 2]; o += n_ftw * 2
    ft_b = raw[o:o + n_ftb * 2]; o += n_ftb * 2
    out_w = raw[o:o + n_ow * 2]; o += n_ow * 2
    out_b, = struct.unpack_from("<h", raw, o)      # widen i16 -> i32

    with open(a.out, "wb") as f:
        f.write(b"RUKN")
        f.write(struct.pack("<6I", 1, INPUT, hl, QA, QB, SCALE))
        f.write(ft_w); f.write(ft_b); f.write(out_w)
        f.write(struct.pack("<i", out_b))

    size = pathlib.Path(a.out).stat().st_size
    print(f"wrote {a.out}  hl={hl}  {size:,} bytes  out_bias={out_b}")
    print("verify: sgurr_cpp/nnue_selfcheck.exe, then bench against gen9")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
