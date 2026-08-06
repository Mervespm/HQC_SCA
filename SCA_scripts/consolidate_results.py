#!/usr/bin/env python3
"""Consolidate every paper-worthy value produced in this campaign into ONE CSV
(paper_key_results.csv) plus a short markdown table, so nothing is lost.

Pulls from:
  paper_results/fix7_device.csv       (device A/B oracle accuracy + peak |t|)
  paper_results/fix7_construction.csv (offline HW-model construction sweep)
  paper_results/soft_vs_hard.csv      (amplification: soft vs hard vote)
  oracle_msgs_meta.json / _sys        (class HW distributions)

Each row: metric, value, unit, source, note
"""
import os
import csv
import json

HERE = os.path.dirname(os.path.abspath(__file__))
PR = os.path.join(HERE, "paper_results")


def read_csv(name):
    p = os.path.join(PR, name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return list(csv.DictReader(f))


def read_json(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return {}
    with open(p) as f:
        return json.load(f)


def main():
    rows = []

    def add(metric, value, unit, source, note):
        rows.append(dict(metric=metric, value=value, unit=unit,
                         source=source, note=note))

    # ---- single-query oracle (device) ----
    dev = {r["pool"]: r for r in read_csv("fix7_device.csv")}
    if "baseline" in dev:
        add("single_query_oracle_acc_baseline", dev["baseline"]["test_acc"],
            "fraction", "fix7_device.csv",
            "device CW310 HQC-G, m'=0 vs decode-failure, fillers anywhere")
        add("peak_tvla_t_baseline", dev["baseline"]["peak_t"], "abs_t",
            "fix7_device.csv", "Welch |t|, baseline ciphertext")
    if "sys" in dev:
        add("single_query_oracle_acc_fix7", dev["sys"]["test_acc"],
            "fraction", "fix7_device.csv",
            "device CW310 HQC-G, fix #7 systematic-region fillers")
        add("peak_tvla_t_fix7", dev["sys"]["peak_t"], "abs_t",
            "fix7_device.csv", "Welch |t|, fix #7 ciphertext (stronger leak)")

    # ---- construction sweep (offline HW model) ----
    con = {r["variant"]: r for r in read_csv("fix7_construction.csv")}
    if con:
        any_r = next(iter(con.values()))
        add("boundary_word_success_rate", any_r["bw_success_rate"], "fraction",
            "fix7_construction.csv",
            "make_boundary_word() probeable-pivot rate (40% unprobeable)")
    for v, r in con.items():
        add(f"model_oracle_acc_{v}", r["model_acc"], "fraction",
            "fix7_construction.csv",
            f"HW-model acc; d'={r['d_prime']}, class0 HW {r['hw0_mean']}, "
            f"class1 HW {r['hw1_mean']}")

    # ---- class HW distributions ----
    for tag, fn in [("baseline", "oracle_msgs_meta.json"),
                    ("fix7_sys", "oracle_msgs_sys_meta.json")]:
        m = read_json(fn)
        if m:
            add(f"class0_success_HW_mean_{tag}", round(m["class0_hw_mean"], 2),
                "bits", fn, "success m' Hamming weight (128-bit)")
            add(f"class1_failure_HW_mean_{tag}", round(m["class1_hw_mean"], 2),
                "bits", fn, "decode-failure m' Hamming weight (128-bit)")

    # ---- amplification: queries R to reach >=99% full key ----
    svh = read_csv("soft_vs_hard.csv")
    for p in sorted(set(r["p"] for r in svh)):
        sub = [r for r in svh if r["p"] == p]
        for scheme in ("hard_key", "soft_key"):
            hit = next((r for r in sub if float(r[scheme]) >= 0.99), None)
            if hit:
                add(f"R_for_99pct_key_{scheme.split('_')[0]}_p{p}",
                    hit["R"], "queries/bit", "soft_vs_hard.csv",
                    f"min R for >=99% full-key at oracle p={p}, d'={hit['d_prime']}")

    # ---- amplification per-bit accuracy after voting (headline) ----
    best = max((r for r in svh), key=lambda r: float(r["soft_bit"]), default=None)
    if best:
        add("per_bit_acc_after_voting_max", round(float(best["soft_bit"]), 5),
            "fraction", "soft_vs_hard.csv",
            "per-secret-bit accuracy after soft combining (approaches 1.0)")

    out = os.path.join(PR, "paper_key_results.csv")
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["metric", "value", "unit", "source", "note"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out}  ({len(rows)} metrics)")
    # also a compact markdown table
    md = os.path.join(PR, "paper_key_results.md")
    with open(md, "w") as f:
        f.write("| metric | value | unit | note |\n|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['metric']} | {r['value']} | {r['unit']} | {r['note']} |\n")
    print(f"wrote {md}")
    for r in rows:
        print(f"  {r['metric']:42s} = {r['value']} {r['unit']}")


if __name__ == "__main__":
    main()
