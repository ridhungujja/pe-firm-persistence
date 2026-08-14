"""Find fund names where the numeral strip in `normalise_firm_ids` misfires.

Run:  python analysis/diagnose_numerals.py

Produces data/numeral_diagnostic.csv, one row per suspect name across both
plans.

Two distinct failures, which need opposite fixes:

CONSUMED  The trailing token was a share-class letter, not a fund number, and
          the regex ate it because the letter is also a roman numeral. The
          character class is [IVXLC], so classes C, I, L, V and X are at risk;
          D and M are NOT, despite being roman digits, because they are absent
          from the class. "BDC III C LP" loses the C, leaving stem "BDC III"
          with the fund number stranded. Every fund in such a series lands on
          its own stem.

STRANDED  The strip failed entirely because something followed the number --
          a parenthetical class, a feeder tag, a domicile suffix -- so the
          number is still sitting in the stem. Same consequence.

Both are splits: one series scattered across several stems, each looking like
a first-time fund and contributing nothing to the persistence regression. The
fix is a row in data/firm_overrides.csv, never a looser regex; the regex
cannot distinguish a share class from a strategy suffix, which is exactly why
the decisions are recorded by hand.
"""

from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.base import (  # noqa: E402
    load_firm_overrides,
    normalise_firm_ids,
    resolve_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "numeral_diagnostic.csv"

#: The character class the strip actually uses. D and M are roman digits but
#: are not in it, so a trailing "D" or "M" class is never consumed.
STRIPPABLE_LETTERS = set("IVXLC")

_ROMAN = re.compile(r"^(?=[IVXLC])C{0,3}(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ROMAN_DIGITS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def _roman_value(token: str) -> int:
    total = 0
    for i, ch in enumerate(token):
        value = _ROMAN_DIGITS[ch]
        nxt = _ROMAN_DIGITS.get(token[i + 1]) if i + 1 < len(token) else None
        total += -value if nxt and nxt > value else value
    return total


def stranded_number(stem: str) -> str:
    """A fund number still sitting in the stem after normalisation."""
    for token in re.split(r"\s+", stem.strip())[1:]:
        head = token.split("-")[0]
        if not head:
            continue
        if head.isdigit():
            value = int(head)
        elif _ROMAN.match(head):
            value = _roman_value(head)
        else:
            continue
        if 0 < value <= 60:
            return token
    return ""


def removed_tail(name: str, stem: str) -> str:
    """What normalisation discarded from the end of the name."""
    cleaned = re.sub(r"[,\.]", "", str(name)).strip().upper()
    return cleaned[len(stem):].strip() if cleaned.startswith(stem) else ""


def diagnose(df: pd.DataFrame, source: str) -> pd.DataFrame:
    stems = normalise_firm_ids(df)
    rows = []
    for name, stem in zip(df["fund_name"], stems):
        tail = removed_tail(name, stem)
        stranded = stranded_number(stem)

        # The tail with entity words dropped: what the numeral strip actually took.
        token = re.sub(r"\b(?:LP|LLC|LTD)\b", "", tail).strip()

        consumed_class = (
            len(token) == 1
            and token in STRIPPABLE_LETTERS
            and bool(stranded)
        )
        if not (consumed_class or stranded):
            continue
        rows.append(
            {
                "source": source,
                "fund_name": name,
                "stem": stem,
                "removed_tail": tail,
                "stranded_number": stranded,
                "failure": "CONSUMED+STRANDED" if consumed_class else "STRANDED",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    calpers = pd.read_csv(resolve_snapshot(DATA, "calpers"))
    oregon_files = sorted(glob.glob(str(DATA / "snapshots" / "oregon_*.csv")))
    oregon = (
        pd.concat([pd.read_csv(p) for p in oregon_files], ignore_index=True)
        .drop_duplicates(subset=["fund_name"])
        if oregon_files
        else pd.DataFrame(columns=["fund_name"])
    )

    print(f"CalPERS names: {len(calpers)}   Oregon distinct names: {len(oregon)}")

    report = pd.concat(
        [diagnose(calpers, "CalPERS"), diagnose(oregon, "Oregon")], ignore_index=True
    )
    report.to_csv(OUT, index=False)

    consumed = report[report["failure"] == "CONSUMED+STRANDED"]
    print(f"\n{len(report)} suspect names "
          f"({len(consumed)} with a share-class letter consumed as a numeral)")

    print("\n--- share-class letter eaten as a roman numeral ---")
    if consumed.empty:
        print("  none")
    for _, r in consumed.iterrows():
        print(f"  [{r['source']:7}] {r['fund_name']:52} -> {r['stem']}  "
              f"(ate '{r['removed_tail']}')")

    # Which of these are already handled?
    overrides = load_firm_overrides()
    known = set(overrides["firm_id_raw"])
    unresolved = report[~report["stem"].isin(known)]

    print(f"\n--- stranded fund numbers not covered by an override "
          f"({unresolved['stem'].nunique()} distinct stems) ---")
    for source, group in unresolved.groupby("source"):
        print(f"  {source}: {group['stem'].nunique()} stems, {len(group)} names")

    print("\n  CalPERS stems still unresolved:")
    cal_un = unresolved[unresolved["source"] == "CalPERS"]
    for stem, group in sorted(cal_un.groupby("stem")):
        print(f"    {stem:52} {' | '.join(group['fund_name'].head(3))}")

    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
