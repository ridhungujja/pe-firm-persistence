"""Generate the fund-family review sheet from the current snapshot.

Run:  python analysis/build_family_review.py

Writes data/family_review.csv: one row per candidate family, carrying the
member fund names and the diagnostics that flag a family as suspect. This is
the worksheet for README roadmap step 2 -- hand-check the largest firms --
and the decisions it produces belong in data/firm_overrides.csv.

The stem rule in `normalise_firm_ids` fails in two directions and the sheet
separates them, because they need opposite fixes:

    SPLIT     one series scattered over several stems, because a share class
              ("(A)", "-C"), a feeder tag ("L.P.1") or a domicile suffix
              ("SCSp") sat after the fund number and blocked the numeral
              strip. Fix by merging.

    OVERMERGE two distinct strategies under one stem, because the token that
              distinguished them was eaten. Fix by splitting.

A split family understates a GP's track record and silently deletes usable
observations from the persistence regression; an over-merged family invents
a track record that no single team produced. Neither is visible in the
snapshot without looking at the names.
"""

from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pefund.ingest.base import (  # noqa: E402
    load_firm_overrides,
    resolve_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "data" / "family_review.csv"

#: Tokens that mark a vehicle as something other than a step in the flagship
#: sequence. Their presence is a reason NOT to merge on name similarity.
SIDECAR_TOKENS = (
    "CO-INVEST",
    "COINVEST",
    "ANNEX",
    "SEED",
    "GROWTH",
    "OPPORTUNIT",
    "SURGE",
    "SELECT",
    "ENCORE",
    "OVERAGE",
    "CONTINUATION",
)


def _residual(name: str) -> str:
    """Fund name with punctuation, entity suffix and fund number removed.

    Mirrors `normalise_firm_ids` but keeps the discarded tail so the sheet can
    show what the stem rule actually ate.
    """
    s = re.sub(r"[,\.]", "", str(name))
    s = re.sub(r"\s+(?:L\.?P\.?|LLC|Ltd|Fund|Partners)?\s*$", "", s)
    s = re.sub(r"\s+(?:[IVXLC]+|\d+)\s*$", "", s)
    return s.strip().upper()


def _dangling(stem: str) -> bool:
    """Stem left ending in a separator or a stray connective."""
    return bool(re.search(r"(?:[-&/]|\bNO|\bTHE|\bAND|\bOF)\s*$", stem.strip()))


#: Well-formed roman numeral, so that acronyms built from the same letters
#: ("CVC", "VIP", "LIV") are not read as fund numbers.
_ROMAN = re.compile(r"^(?=[IVXLC])C{0,3}(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def _orphan_number(stem: str) -> str:
    """A fund number still sitting in the stem, i.e. the numeral strip failed.

    This is the crisp signature of a split family: `normalise_firm_ids` only
    removes a trailing number, so anything that follows the number -- a share
    class, a feeder tag, an SCSp suffix -- leaves the number embedded and
    every vintage of the series lands on its own stem.
    """
    # Skip the first token: a leading number belongs to the firm's name
    # ("57 Stars", "2024 Golden Bay"), never to a fund sequence.
    for tok in re.split(r"\s+", stem.strip())[1:]:
        head = tok.split("-")[0]
        if not head:
            continue
        if head.isdigit():
            value = int(head)
        elif _ROMAN.match(head):
            value = _roman_value(head)
        else:
            continue
        # No GP in this universe is on fund 60. Anything larger is an acronym
        # or a year that happens to be spellable in roman letters.
        if 0 < value <= 60:
            return tok
    return ""


def _roman_value(token: str) -> int:
    digits = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total = 0
    for i, ch in enumerate(token):
        v = digits[ch]
        nxt = digits.get(token[i + 1]) if i + 1 < len(token) else None
        total += -v if nxt and nxt > v else v
    return total


def build(snapshot: pd.DataFrame, overrides: pd.DataFrame) -> pd.DataFrame:
    raw_col = "firm_id_raw" if "firm_id_raw" in snapshot.columns else "firm_id"
    df = snapshot.copy()
    df["_raw"] = df[raw_col]
    df["_final"] = df["firm_id"]

    decided = dict(zip(overrides["firm_id_raw"], overrides["decision"]))
    reasons = dict(zip(overrides["firm_id_raw"], overrides["reason"]))

    # Stems that look like fragments of a longer stem. This is the detector
    # for both failure modes: whether the pair is a split or two genuinely
    # different strategies is exactly the judgement the sheet asks for.
    raws = sorted(df["_raw"].unique())
    neighbours: dict[str, set[str]] = {r: set() for r in raws}
    for a, b in itertools.combinations(raws, 2):
        if b.startswith(a + " ") or a.startswith(b + " "):
            neighbours[a].add(b)
            neighbours[b].add(a)

    rows = []
    for raw, sub in df.groupby("_raw"):
        sub = sub.sort_values("vintage")
        names = list(sub["fund_name"])
        finals = sorted(set(sub["_final"]))
        residuals = sorted({_residual(n) for n in names})
        orphan = _orphan_number(raw)
        sidecars = {any(t in n.upper() for t in SIDECAR_TOKENS) for n in names}

        flags = []
        if len(residuals) > 1:
            flags.append("overmerge:members disagree after removing fund number")
        if len(sidecars) > 1:
            flags.append("overmerge:sidecar pooled with flagship")
        if orphan:
            flags.append(f"split:fund number '{orphan}' stranded in the stem")
        if _dangling(raw):
            flags.append("split:stem ends in a dangling separator")
        if orphan and neighbours[raw]:
            flags.append("split:sibling stem carries the same series name")
        if sub.duplicated(subset=["vintage"], keep=False).any():
            flags.append("sequence:two funds share a vintage")

        rows.append(
            {
                "firm_id_raw": raw,
                "firm_id_final": finals[0] if len(finals) == 1 else "|".join(finals),
                "n_funds_raw": len(sub),
                "vintages": ";".join(str(int(v)) for v in sub["vintage"]),
                "fund_names": " | ".join(names),
                "orphan_number": orphan,
                "neighbour_stems": " | ".join(sorted(neighbours[raw])),
                "flags": " ; ".join(flags),
                "decision": decided.get(raw, "unreviewed"),
                "reason": reasons.get(raw, ""),
            }
        )

    out = pd.DataFrame(rows)
    final_sizes = df.groupby("_final").size()
    out["n_funds_final"] = out["firm_id_final"].map(final_sizes).fillna(0).astype(int)
    out["needs_review"] = (out["decision"] == "unreviewed") & (out["flags"] != "")
    return out.sort_values(
        ["needs_review", "n_funds_final", "firm_id_final"], ascending=[False, False, True]
    ).reset_index(drop=True)


def main() -> None:
    snapshot = pd.read_csv(resolve_snapshot(DATA, "calpers"))
    overrides = load_firm_overrides()
    review = build(snapshot, overrides)
    review.to_csv(OUT, index=False)

    n_merge = (overrides["decision"] == "merge").sum()
    n_keep = (overrides["decision"] == "keep_separate").sum()
    print(f"{len(review)} raw stems over {len(snapshot)} funds")
    print(f"{n_merge} merge overrides, {n_keep} reviewed-and-kept-separate")
    print(f"{int(review['needs_review'].sum())} flagged stems still unreviewed")

    over = review[review["flags"].str.contains("overmerge", na=False)]
    print(f"\n{len(over)} stems flagged as possible over-merges")
    for _, r in over.iterrows():
        print(f"  {r.firm_id_raw}: {r.fund_names}")

    raw_pairs = int((snapshot.groupby("firm_id_raw").size() - 1).clip(lower=0).sum())
    fin_pairs = int((snapshot.groupby("firm_id").size() - 1).clip(lower=0).sum())
    print(
        f"\nUsable persistence observations: {raw_pairs} on raw stems -> "
        f"{fin_pairs} after overrides"
    )
    print(f"\nWrote {OUT}")


if __name__ == "__main__":
    main()
