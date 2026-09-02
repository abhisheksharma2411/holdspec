"""Generate every LaTeX table in the paper from the JSON under results/.

No number in the paper is typed by hand. Run this after the experiments and
before latexmk; `make paper` does both.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
RESULTS = REPO / "results"
TABLES = Path(__file__).resolve().parent / "tables"

from holdspec.profiles import ALL_PROFILES  # noqa: E402

PRETTY = {
    "stripe_card_default": "Stripe, card default",
    "stripe_multicapture": "Stripe, multicapture",
    "stripe_overcapture": "Stripe, overcapture",
    "adyen_card_default": "Adyen, card default",
    "adyen_multiple_partial_captures": "Adyen, multiple partial captures",
    "incremental_auth": "Incremental auth (synthetic)",
}


def esc(text: str) -> str:
    for a, b in (("\\", r"\textbackslash{}"), ("_", r"\_"), ("%", r"\%"),
                 ("&", r"\&"), ("#", r"\#")):
        text = text.replace(a, b)
    return text


def load(name: str):
    return json.loads((RESULTS / name).read_text())


def write(name: str, body: str) -> None:
    TABLES.mkdir(parents=True, exist_ok=True)
    (TABLES / name).write_text(body.rstrip() + "\n")
    print(f"  {name}")


def table_profiles() -> None:
    rows = []
    for p in ALL_PROFILES:
        caps = int(p.documented_max_captures)
        cap_text = "not fixed" if caps < 0 else str(caps)
        rows.append(
            " & ".join(
                [
                    PRETTY[p.name],
                    f"{p.documented_validity_days:g}",
                    cap_text,
                    f"{p.documented_over_capture_pct:g}\\%",
                    "yes" if p.supports_final_capture else "no",
                    "yes" if p.void_after_partial else "no",
                    esc(p.remainder_release_mechanism),
                ]
            )
            + r" \\"
        )
    body = r"""\begin{tabular}{lccccccl}
\toprule
Profile & Validity & Captures & Over- & Final- & Void after & Remainder released by \\
        & (days)   & allowed  & capture & capture flag & partial capture & \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}"""
    write("tab_profiles.tex", body)


def table_model_check() -> None:
    data = load("e1_model_check.json")
    rows = []
    for r in data["profiles"]:
        rows.append(
            " & ".join(
                [
                    PRETTY[r["profile"]],
                    f"{r['states_generated']:,}",
                    f"{r['distinct_states']:,}",
                    str(r["diameter"]),
                    f"{r['seconds']:.1f}",
                    "pass" if r["ok"] else esc(str(r["violated"])),
                ]
            )
            + r" \\"
        )
    body = r"""\begin{tabular}{lrrrrl}
\toprule
Profile & States & Distinct & Depth & Time (s) & Verdict \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}"""
    write("tab_model_check.tex", body)


def table_spec_mutation() -> None:
    data = load("e2_spec_mutation.json")
    rows = []
    for r in data:
        rows.append(
            " & ".join(
                [
                    esc(r["mutation"].split("_", 1)[0]),
                    esc(r["description"]),
                    r"\texttt{" + esc(r["expected_property"].replace("INV_", "").replace("LIVE_", "")) + "}",
                    "yes" if r["caught_by_expected_property_alone"] else "no",
                    str(r["counterexample_length"] or "--"),
                ]
            )
            + r" \\"
        )
    body = r"""\begin{tabular}{llllr}
\toprule
& Change made to the specification & Property targeted & Caught & Trace \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}"""
    write("tab_spec_mutation.tex", body)


def table_conformance() -> None:
    data = load("e3_conformance.json")
    rows = []
    for r in data["per_profile"]:
        s, d = r["suites"], r["detection_rate"]
        rows.append(
            " & ".join(
                [
                    PRETTY[r["profile"]],
                    str(r["killable_mutants"]),
                    str(r["equivalent_mutants"]),
                    f"{s['model']['tests']:,}",
                    f"{s['model']['api_calls']:,}",
                    f"{d['model']:.2f}",
                    f"{d['random']:.2f}",
                    f"{d['random_10x']:.2f}",
                    f"{d['handwritten']:.2f}",
                ]
            )
            + r" \\"
        )
    o = data["overall"]
    total = (
        r"\midrule" + "\n"
        + " & ".join(
            [
                r"\textbf{All profiles}",
                r"\textbf{" + str(o["model"]["killable"]) + "}",
                "",
                "",
                "",
                r"\textbf{" + f"{o['model']['rate']:.2f}" + "}",
                f"{o['random']['rate']:.2f}",
                f"{o['random_10x']['rate']:.2f}",
                f"{o['handwritten']['rate']:.2f}",
            ]
        )
        + r" \\"
    )
    body = r"""\begin{tabular}{lrrrrrrrr}
\toprule
& \multicolumn{2}{c}{Mutants} & \multicolumn{2}{c}{Model suite} & \multicolumn{4}{c}{Fraction detected} \\
\cmidrule(lr){2-3}\cmidrule(lr){4-5}\cmidrule(lr){6-9}
Profile & killable & equiv. & tests & calls & model & random & random$\times$10 & hand \\
\midrule
""" + "\n".join(rows) + "\n" + total + r"""
\bottomrule
\end{tabular}"""
    write("tab_conformance.tex", body)


def _compact(witness: str) -> str:
    """Shorten a witness so it fits a table cell without losing what it says.

    advance_time(1) becomes wait; capture(n, final=True) becomes cap(n,fin) and
    the non-final form cap(n,part). The caption spells the shorthand out.
    """
    parts = []
    for call in witness.split(" ; "):
        call = call.strip()
        if call.startswith("advance_time"):
            parts.append("wait")
        elif call.startswith("authorize"):
            parts.append("auth" + call[len("authorize"):])
        elif call.startswith("capture"):
            inner = call[len("capture("):-1]
            amount, final = [x.strip() for x in inner.split(",")]
            parts.append(f"cap({amount},{'fin' if final.endswith('True') else 'part'})")
        else:
            parts.append(call.replace("()", ""))
    # Collapse runs of waits: "wait x3" reads better than three of them.
    out, i = [], 0
    while i < len(parts):
        j = i
        while j < len(parts) and parts[j] == "wait":
            j += 1
        run = j - i
        if run > 1:
            out.append(f"wait$\\times${run}")
            i = j
        else:
            out.append(parts[i])
            i += 1
    return " ; ".join(out)


def table_divergences() -> None:
    data = load("e4_cross_provider.json")
    lines = []
    for pair in data["highlighted_pairs"]:
        header = (r"\textit{" + esc(PRETTY[pair["left"]]) + r"} (left) vs.\ \textit{"
                  + esc(PRETTY[pair["right"]]) + r"} (right)")
        lines.append(r"\multicolumn{4}{l}{" + header + r"} \\")
        for d in pair["divergences"]:
            if d["field"] == "accepted":
                amounts = ", ".join(str(a) for a in d["amounts"])
                what = d["op_kind"]
                if d["op_kind"] == "capture":
                    what += " (final)" if d["op_final"] else " (non-final)"
                    what += f", amount {amounts}"
                left, right = d["left"], d["right"]
            else:
                what = d["op_kind"]
                left = "; ".join(f"{a['attribute']} {a['left']}" for a in d["differing"])
                right = "; ".join(f"{a['attribute']} {a['right']}" for a in d["differing"])
            lines.append(
                " & ".join([
                    esc(what), esc(left), esc(right),
                    r"\texttt{\scriptsize " + _compact(d["witness"]) + "}",
                ])
                + r" \\"
            )
        lines.append(r"\addlinespace")
    body = r"""\begin{tabular}{p{3.0cm}p{2.5cm}p{2.5cm}p{7.4cm}}
\toprule
Call & Left provider & Right provider & Shortest witness \\
\midrule
""" + "\n".join(lines[:-1]) + r"""
\bottomrule
\end{tabular}"""
    write("tab_divergences.tex", body)


def table_http() -> None:
    data = load("e6_http_conformance.json")
    rows = []
    for r in data:
        detected = sum(1 for d in r["injected_defects"] if d["detected"])
        rows.append(
            " & ".join(
                [
                    PRETTY[r["profile"]],
                    esc(r["api_shape"]),
                    f"{r['clean_run']['tests']:,}",
                    f"{r['clean_run']['api_calls']:,}",
                    "conforms" if r["conforms"] else "fails",
                    f"{detected}/{len(r['injected_defects'])}",
                ]
            )
            + r" \\"
        )
    body = r"""\begin{tabular}{llrrcc}
\toprule
Profile & Shape & Tests & Calls & Clean & Found \\
\midrule
""" + "\n".join(rows) + r"""
\bottomrule
\end{tabular}"""
    write("tab_http.tex", body)


def macros() -> None:
    """Single numbers quoted in the prose, so those are generated too."""
    e1, e2 = load("e1_model_check.json"), load("e2_spec_mutation.json")
    e3, e4 = load("e3_conformance.json"), load("e4_cross_provider.json")
    e5, e6 = load("e5_equivalence.json"), load("e6_http_conformance.json")
    corpus = load("defect_corpus.json")
    o = e3["overall"]
    total_states = sum(r["distinct_states"] for r in e1["profiles"])
    defs = {
        "numprofiles": len(e1["profiles"]),
        "totaldistinctstates": f"{total_states:,}",
        "largeststatespace": f"{max(r['distinct_states'] for r in e1['profiles']):,}",
        "checkseconds": f"{sum(r['seconds'] for r in e1['profiles']):.1f}",
        "numspecmutations": len(e2),
        "specmutationscaught": sum(1 for r in e2 if r["caught_by_expected_property_alone"]),
        "specmutationssurvived": sum(1 for r in e2 if not r["caught_by_any_property"]),
        "killablemutants": o["model"]["killable"],
        "modeldetected": o["model"]["detected"],
        "modelrate": f"{o['model']['rate'] * 100:.0f}",
        "randomrate": f"{o['random']['rate'] * 100:.0f}",
        "randomtenxrate": f"{o['random_10x']['rate'] * 100:.0f}",
        "handrate": f"{o['handwritten']['rate'] * 100:.0f}",
        "equivmutants": sum(r["equivalent_mutants"] for r in e3["per_profile"]),
        "numpairs": len(e4["all_pairs"]),
        "pairswithdivergence": sum(1 for r in e4["all_pairs"] if r["divergence_classes"] > 0),
        "maxdivergences": max(r["divergence_classes"] for r in e4["all_pairs"]),
        "equivalenceprofiles": sum(1 for r in e5 if r["identical"]),
        "httpdeployments": len(e6),
        "httpconforming": sum(1 for r in e6 if r["conforms"]),
        "httpinjected": sum(len(r["injected_defects"]) for r in e6),
        "httpinjecteddetected": sum(
            1 for r in e6 for d in r["injected_defects"] if d["detected"]
        ),
        "corpusrows": len(corpus),
        # Filled in by PUBLISH.md step 2. Kept here so the paper never carries a
        # hand-edited number, not even this one.
        "zenodocode": (Path(__file__).parent / "zenodo_doi.txt").read_text().strip()
        if (Path(__file__).parent / "zenodo_doi.txt").exists()
        else "10.5281/zenodo.PENDING",
    }
    body = "\n".join(rf"\newcommand{{\{k}}}{{{v}}}" for k, v in defs.items())
    write("macros.tex", body)


def main() -> int:
    print("generating tables from results/")
    table_profiles()
    table_model_check()
    table_spec_mutation()
    table_conformance()
    table_divergences()
    table_http()
    macros()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
