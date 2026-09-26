#!/usr/bin/env python3
"""Count how calibration games ended, from the PGN files themselves.

fastchess writes the reason into the last move comment ("..., White mates}").
A game that ended any other way, such as a time loss, an illegal move or a
crash, makes a rating untrustworthy (METHODOLOGY 9).

    python testing/pgn_endings.py FILE.pgn [FILE.pgn ...]

Prints "total abnormal" on the first line, then each abnormal ending.
"""
import re
import sys

NORMAL = re.compile(r"(White|Black) mates$|^Draw by ")

total, abnormal = 0, []
for path in sys.argv[1:]:
    text = open(path, encoding="utf-8", errors="replace").read()
    for game in re.split(r"(?=\[Event )", text):
        if "[Result" not in game:
            continue
        total += 1
        body = game.split("\n\n", 1)[1] if "\n\n" in game else ""
        comments = re.findall(r"\{([^}]*)\}", body, flags=re.S)
        reason = " ".join(comments[-1].split()).rsplit(", ", 1)[-1] if comments else "no comment"
        if not NORMAL.search(reason):
            white = re.search(r'\[White "([^"]*)"\]', game).group(1)
            black = re.search(r'\[Black "([^"]*)"\]', game).group(1)
            abnormal.append(f"{white} vs {black}: {reason}")
print(total, len(abnormal))
for line in abnormal:
    print("  " + line)
