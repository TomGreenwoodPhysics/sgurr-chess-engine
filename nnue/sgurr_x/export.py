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

QB, SCALE, INPUT = 64, 400, 768


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("quantised")
    ap.add_argument("out")
    ap.add_argument("--hl", type=int, default=1024)
    ap.add_argument("--qa", type=int, default=255,
                    help="accumulator scale; must match the engine's SGR_QA "
                         "and the quantisation used when training")
    ap.add_argument("--bucket-map", default=None,
                    help="comma-separated 64 entries; writes a version-2 "
                         "king-bucketed net instead of version 1")
    a = ap.parse_args()

    hl, QA = a.hl, a.qa
    raw = pathlib.Path(a.quantised).read_bytes()

    if a.bucket_map:
        bmap = [int(x) for x in a.bucket_map.split(",")]
        if len(bmap) != 64:
            print(f"bucket map has {len(bmap)} entries, need 64", file=sys.stderr)
            return 1
        nbuckets = max(bmap) + 1
        version, n_inputs = 2, INPUT * nbuckets
    else:
        bmap, nbuckets, version, n_inputs = None, 1, 1, INPUT

    n_ftw, n_ftb, n_ow = n_inputs * hl, hl, 2 * hl
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
        f.write(struct.pack("<6I", version, n_inputs, hl, QA, QB, SCALE))
        if bmap is not None:
            f.write(bytes(bmap))
        f.write(ft_w); f.write(ft_b); f.write(out_w)
        f.write(struct.pack("<i", out_b))

    size = pathlib.Path(a.out).stat().st_size
    print(f"wrote {a.out}  v{version}  hl={hl}  buckets={nbuckets}  "
          f"qa={QA}  {size:,} bytes  out_bias={out_b}")
    print("verify: sgurr_cpp/nnue_selfcheck.exe, then bench against gen9")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
