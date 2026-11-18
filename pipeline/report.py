"""Turn any results file in the shared columns into all of our charts.

Usage:
    python pipeline/report.py results/<run>/results.csv
    python pipeline/report.py results/<run>/results.csv --check-links   # also test cited links (needs internet)

Writes results/<run>/report/  (one PNG per chart + summary.md)
and adds/updates this run's line in results/run_log.csv (total tokens and cost per run).

A chart is skipped, with the reason written in summary.md, when the file can't support
it (e.g. nothing is scored yet, or only one mode was run).
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checks import CAVEAT_ELEMENTS, caveat_check, caveat_text, check_links_in_results  # noqa: E402
from common import NUMBER_SCORES, REPO_ROOT, RESULT_COLUMNS, clean_score, to_bool  # noqa: E402

# ------------------------------------------------------------------ settings you may edit

HAIKU_PAIR = ("haiku-4.5", "haiku-5.5")   # model names as they appear in the results file
MODE_ORDER = ["cold", "skill", "mcp"]
# Week 2 IDs carry the question type in their first letter.
ID_PREFIX_TYPES = {"N": "Naive public", "R": "Academic researcher", "P": "Policy analyst",
                   "T": "Team-written (T)"}

# ------------------------------------------------------------------ look (dataviz palette)

SURFACE, INK, INK_2, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SCORE_COLORS = {"Correct": "#0ca30c", "Close": "#fab219", "Wrong": "#d03b3b", "No number": "#b9b8b0"}
OFF_ON = {"off": "#b9b8b0", "on": "#2a78d6"}
BLUES = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "text.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "legend.frameon": False,
})


# ------------------------------------------------------------------ loading

def load(path):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c in RESULT_COLUMNS if c not in df.columns]
    if missing:
        sys.exit(f"{path} is missing shared columns: {missing}")
    for c in ["number_score", "year_score", "source_score"]:
        df[c] = df[c].map(clean_score)
    for c in ["thinking", "web_search", "searched"]:
        df[c] = df[c].map(to_bool)
    for c in ["input_tokens", "output_tokens", "cost", "seconds"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["total_tokens"] = df["input_tokens"] + df["output_tokens"]
    df["scored"] = df["number_score"] != ""
    df["correct"] = (df["number_score"] == "Correct").astype(float)
    df["correct_or_close"] = df["number_score"].isin(["Correct", "Close"]).astype(float)

    checks = pd.DataFrame([caveat_check(caveat_text(r)) for _, r in df.iterrows()], index=df.index)
    df = pd.concat([df, checks], axis=1)
    return add_question_types(df)


def add_question_types(df):
    """Join prompt metadata (user_type, style, wording, detail) by id."""
    meta = []
    for path in (REPO_ROOT / "prompts").glob("*.csv"):
        try:
            m = pd.read_csv(path, dtype=str, keep_default_na=False)
        except pd.errors.EmptyDataError:
            continue
        if "id" in m.columns and len(m):
            meta.append(m)
    cols = ["user_type", "style", "wording", "detail", "leading"]
    if meta:
        meta = pd.concat(meta).drop_duplicates("id").set_index("id")
        for c in cols:
            df[c] = df["id"].map(meta[c]) if c in meta.columns else np.nan
    else:
        for c in cols:
            df[c] = np.nan
    prefix = df["id"].str[:1].map(ID_PREFIX_TYPES)
    df["user_type"] = df["user_type"].fillna(prefix).replace("", np.nan).fillna(prefix)
    pairs_file = REPO_ROOT / "notes" / "sophia_pairs.json"
    df["pair_axis"] = pd.Series([None] * len(df), index=df.index, dtype=object)
    if pairs_file.exists():
        for p in json.loads(pairs_file.read_text()):
            df.loc[df["id"].isin([p["baseline_id"], p["variant_id"]]), "pair_axis"] = p["axis"]
    return df


# ------------------------------------------------------------------ helpers

def model_colors(df):
    return {m: SERIES[i % len(SERIES)] for i, m in enumerate(pd.unique(df["model"]))}


def pct_axis(ax, axis="y"):
    fmt = matplotlib.ticker.PercentFormatter(1.0, decimals=0)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def save(fig, out_dir, name):
    path = out_dir / f"{name}.png"
    fig.savefig(path, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return path


def bar_labels(ax, bars, values, fmt="{:.0%}", ns=None):
    for i, (b, v) in enumerate(zip(bars, values)):
        if pd.isna(v):
            continue
        label = fmt.format(v) + (f"\nn={ns[i]}" if ns is not None else "")
        ax.annotate(label, (b.get_x() + b.get_width() / 2, b.get_height()),
                    xytext=(0, 3), textcoords="offset points", ha="center", va="bottom",
                    fontsize=8, color=INK_2)


def paired(df, factor):
    """Keep only rows whose twin (same model, prompt and other settings) has the other value
    of `factor`, so on-vs-off compares like with like."""
    keys = [c for c in ["id", "model", "mode", "thinking", "web_search", "repeat"] if c != factor]
    d = df[df[factor].notna()].copy()
    d["_k"] = d[keys].apply(lambda col: col.map(str)).agg("|".join, axis=1)
    both = d.groupby("_k")[factor].nunique()
    return d[d["_k"].isin(both[both == 2].index)]


def grouped_bars(ax, table, colors, ns=None, fmt="{:.0%}"):
    """table: index = x groups, columns = series."""
    n_series = len(table.columns)
    width = 0.8 / n_series
    x = np.arange(len(table.index))
    for j, col in enumerate(table.columns):
        vals = table[col].values
        bars = ax.bar(x + (j - (n_series - 1) / 2) * width, np.nan_to_num(vals), width * 0.92,
                      color=colors[col], label=str(col), edgecolor=SURFACE, linewidth=1)
        bar_labels(ax, bars, vals, fmt, None if ns is None else ns[col].values)
    ax.set_xticks(x, table.index)
    ax.grid(axis="x", visible=False)


# ------------------------------------------------------------------ charts
# Each returns (path or None, note). A None path means skipped; the note says why.

def chart_accuracy_by_model(df, out):
    s = df[df.scored]
    if s.empty:
        return None, "Nothing scored yet (number_score is empty)."
    order = s.groupby("model")["correct"].mean().sort_values().index
    shares = (s.groupby("model")["number_score"].value_counts(normalize=True)
              .unstack(fill_value=0).reindex(columns=NUMBER_SCORES, fill_value=0).loc[order])
    ns = s.groupby("model").size().loc[order]
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(order) + 1.6))
    left = np.zeros(len(order))
    for score in NUMBER_SCORES:
        vals = shares[score].values
        ax.barh(range(len(order)), vals, left=left, color=SCORE_COLORS[score], label=score,
                edgecolor=SURFACE, linewidth=1.5, height=0.6)
        for i, v in enumerate(vals):
            if v >= 0.08:
                ax.text(left[i] + v / 2, i, f"{v:.0%}", ha="center", va="center", fontsize=8,
                        color=INK if score in ("Close", "No number") else "white")
        left += vals
    ax.set_yticks(range(len(order)), [f"{m}  (n={ns[m]})" for m in order])
    pct_axis(ax, "x")
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    ax.set_title("How each model's headline number scored")
    ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.12), fontsize=8)
    return save(fig, out, "01_accuracy_by_model"), ""


def cost_per_correct(df):
    """Per model: total cost of scored answers / number of answers scored Correct.
    UNICEF asked for this because tool results (web search, MCP) add tokens, so a cheap-looking
    setup can still cost more per answer you can actually use. NaN when nothing is Correct."""
    s = df[df.scored]
    g = s.groupby("model", sort=False).agg(cost=("cost", lambda c: c.sum(min_count=1)),
                                          n_correct=("correct", "sum"))
    return (g["cost"] / g["n_correct"].replace(0, np.nan)).rename("cost_per_correct")


def chart_cost_by_model(df, out):
    has_cost = df["cost"].fillna(0).sum() > 0
    has_tok = df["total_tokens"].notna().any() and df["total_tokens"].fillna(0).sum() > 0
    if not has_tok and not has_cost:
        return None, "No token or cost data (chat-app runs don't record them)."
    colors = model_colors(df)
    by = df.groupby("model", sort=False)
    panels = []
    if has_cost:
        panels.append(("Average cost per answer (USD)", by["cost"].mean(), "${:.4f}"))
        panels.append(("Total cost of this run (USD)", by["cost"].sum(), "${:.3f}"))
        if df.scored.any():
            cpc = cost_per_correct(df).reindex(by["cost"].mean().index)
            panels.append(("Cost per correct answer (USD)", cpc, "${:.4f}"))
    panels.append(("Average tokens per answer (input + output)", by["total_tokens"].mean(),
                   "{:,.0f}"))
    fig, axes = plt.subplots(1, len(panels), figsize=(4.2 * len(panels), 3.6))
    axes = np.atleast_1d(axes)
    for ax, (title, series, fmt) in zip(axes, panels):
        bars = ax.bar(series.index, series.values, color=[colors[m] for m in series.index],
                      width=0.6)
        bar_labels(ax, bars, series.values, fmt)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", rotation=30)
        ax.grid(axis="x", visible=False)
    note = "" if has_cost else "No cost recorded (all zero), so only tokens are shown."
    return save(fig, out, "02_cost_by_model"), note


def chart_accuracy_vs_cost(df, out):
    s = df[df.scored]
    if s.empty:
        return None, "Nothing scored yet."
    use_cost = s["cost"].fillna(0).sum() > 0
    xcol = "cost" if use_cost else "total_tokens"
    if s[xcol].isna().all() or (s[xcol].fillna(0) == 0).all():
        return None, "No cost or token data to put on the x-axis."
    g = s.groupby("model").agg(acc=("correct", "mean"), x=(xcol, "mean"), n=("correct", "size"))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter(g["x"], g["acc"], s=70, color=SERIES[0], edgecolor=SURFACE, linewidth=2, zorder=3)
    for m, r in g.iterrows():
        ax.annotate(m, (r["x"], r["acc"]), xytext=(7, 4), textcoords="offset points", fontsize=9)
    pct_axis(ax)
    ax.set_ylim(0, 1)
    if use_cost and (g["x"] > 0).all() and g["x"].max() / g["x"].min() > 20:
        ax.set_xscale("log")
    ax.set_xlabel("Average cost per answer (USD)" if use_cost
                  else "Average tokens per answer (no cost recorded)")
    ax.set_ylabel("Share of answers scored Correct")
    ax.set_title("Accuracy vs. cost  (up and to the left is better)")
    return save(fig, out, "03_accuracy_vs_cost"), ""


def chart_question_type(df, out):
    s = df[df.scored]
    if s.empty:
        return None, "Nothing scored yet."
    dims = [("user_type", "Who is asking", s)]
    for axis in ["style", "wording", "detail"]:
        sub = s[s["pair_axis"] == axis] if s["pair_axis"].notna().any() else s
        if sub[axis].replace("", np.nan).nunique() >= 2:
            dims.append((axis, f"{axis.title()} (within {axis} pairs)", sub))
    dims = [d for d in dims if d[2][d[0]].replace("", np.nan).nunique() >= 1]
    if not dims:
        return None, "No question-type information for these IDs."
    fig, axes = plt.subplots(1, len(dims), figsize=(3.8 * len(dims) + 0.5, 3.8), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (col, title, sub) in zip(axes, dims):
        g = sub[sub[col].replace("", np.nan).notna()].groupby(col)["correct"].agg(["mean", "size"])
        bars = ax.bar([str(i).replace(" ", "\n", 1) for i in g.index], g["mean"], color=SERIES[0],
                      width=0.6)
        bar_labels(ax, bars, g["mean"].values, ns=g["size"].values)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="x", visible=False)
        ax.set_ylim(0, 1.12)
        pct_axis(ax)
    axes[0].set_ylabel("Share scored Correct (all models)")
    fig.suptitle("Accuracy by question type", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    return save(fig, out, "04_accuracy_by_question_type"), ""


def chart_on_off(df, out):
    s = df[df.scored]
    if s.empty:
        return None, "Nothing scored yet."
    panels, notes = [], []
    for factor, title in [("thinking", "Thinking"), ("web_search", "Web search")]:
        p = paired(s, factor)
        if p.empty:
            known = s[factor].dropna().unique()
            notes.append(f"{title}: no on/off pairs to compare (values seen: "
                         f"{', '.join(map(str, known)) or 'unknown only'}).")
            continue
        t = p.groupby(["model", factor])["correct"].mean().unstack()
        n = p.groupby(["model", factor]).size().unstack()
        t.columns = n.columns = ["off" if not c else "on" for c in t.columns]
        panels.append((title, t[["off", "on"]], n[["off", "on"]]))
    if not panels:
        return None, " ".join(notes)
    fig, axes = plt.subplots(1, len(panels), figsize=(max(5, 0.9 * len(panels[0][1]) + 2.5)
                                                       * len(panels), 3.9), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (title, t, n) in zip(axes, panels):
        grouped_bars(ax, t, OFF_ON)
        ax.set_title(f"{title} off vs. on", fontsize=10)
        ax.tick_params(axis="x", rotation=30)
        ax.set_ylim(0, 1.12)
        pct_axis(ax)
        ax.legend(loc="upper right", fontsize=8)
    axes[0].set_ylabel("Share scored Correct")
    fig.tight_layout()
    return save(fig, out, "05_thinking_and_web_search_on_vs_off"), " ".join(notes)


def chart_modes(df, out):
    s = df[df.scored]
    if s.empty:
        return None, "Nothing scored yet."
    modes = [m for m in MODE_ORDER if m in set(s["mode"])] + \
        sorted(set(s["mode"]) - set(MODE_ORDER))
    if len(modes) < 2:
        return None, f"Only one mode in this file ({modes[0] if modes else 'none'})."
    t = s.groupby(["model", "mode"])["correct"].mean().unstack()[modes]
    colors = {m: SERIES[i] for i, m in enumerate(modes)}
    fig, ax = plt.subplots(figsize=(max(6, 1.3 * len(t) + 2), 4))
    grouped_bars(ax, t, colors)
    ax.set_ylim(0, 1.12)
    pct_axis(ax)
    ax.set_ylabel("Share scored Correct")
    ax.set_title("Skill vs. cold vs. MCP")
    ax.legend(title="mode", fontsize=8, loc="upper left", bbox_to_anchor=(1, 1))
    return save(fig, out, "06_skill_vs_cold_vs_mcp"), ""


def chart_haiku(df, out):
    present = [m for m in HAIKU_PAIR if m in set(df["model"])]
    if len(present) < 2:
        return None, (f"Needs both {HAIKU_PAIR[0]} and {HAIKU_PAIR[1]} in the model column "
                      f"(found: {', '.join(present) or 'neither'}).")
    d = df[df["model"].isin(present)]
    colors = {present[0]: SERIES[0], present[1]: SERIES[1]}
    panels = []
    if d.scored.any():
        panels.append(("Share scored Correct", d[d.scored].groupby("model")["correct"].mean(),
                       "{:.0%}", True))
    if d["cost"].fillna(0).sum() > 0:
        panels.append(("Average cost per answer (USD)", d.groupby("model")["cost"].mean(),
                       "${:.4f}", False))
    if d["total_tokens"].notna().any():
        panels.append(("Average tokens per answer", d.groupby("model")["total_tokens"].mean(),
                       "{:,.0f}", False))
    fig, axes = plt.subplots(1, len(panels), figsize=(3.4 * len(panels), 3.5))
    axes = np.atleast_1d(axes)
    for ax, (title, series, fmt, is_pct) in zip(axes, panels):
        series = series.reindex(present)
        bars = ax.bar(series.index, series.values, color=[colors[m] for m in series.index],
                      width=0.55)
        bar_labels(ax, bars, series.values, fmt)
        ax.set_title(title, fontsize=10)
        ax.grid(axis="x", visible=False)
        if is_pct:
            ax.set_ylim(0, 1.12)
            pct_axis(ax)
    fig.suptitle(f"{present[0]} vs. {present[1]}", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    return save(fig, out, "07_haiku_4_5_vs_5_5"), ""


def chart_caveats(df, out):
    has_text = (df["answer"].str.strip() != "") | (df["caveat"].str.strip() != "")
    d = df[has_text]
    if d.empty:
        return None, "No answer or caveat text to check."
    t = d.groupby("model", sort=False)[CAVEAT_ELEMENTS].mean()
    labels = ["Estimate\nor range", "Year", "Source", "Definition"]
    fig, ax = plt.subplots(figsize=(6.5, 0.55 * len(t) + 1.8))
    idx = np.clip((t.values * (len(BLUES) - 1)).round().astype(int), 0, len(BLUES) - 1)
    for i in range(t.shape[0]):
        for j in range(t.shape[1]):
            v = t.values[i, j]
            ax.add_patch(plt.Rectangle((j, i), 0.96, 0.92, color=BLUES[idx[i, j]]))
            ax.text(j + 0.48, i + 0.46, f"{v:.0%}", ha="center", va="center", fontsize=9,
                    color="white" if idx[i, j] >= 4 else INK)
    ax.set_xlim(0, t.shape[1])
    ax.set_ylim(t.shape[0], 0)
    ax.set_xticks(np.arange(t.shape[1]) + 0.48, labels)
    ax.set_yticks(np.arange(t.shape[0]) + 0.46, t.index)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0)
    ax.xaxis.tick_top()
    src = "answer text" if (d["answer"].str.strip() != "").any() else "the tester's column P note"
    ax.set_title(f"Share of answers whose caveat covers each element\n(automatic check on {src})",
                 pad=34)
    return save(fig, out, "08_caveat_check"), ""


def chart_year_source(df, out):
    s = df[(df["year_score"] != "") | (df["source_score"] != "")]
    if s.empty:
        return None, "No year or source scores."
    fig, axes = plt.subplots(1, 2, figsize=(11, 0.5 * s["model"].nunique() + 2))
    specs = [("year_score", ["Latest", "Outdated", "None"],
              {"Latest": "#0ca30c", "Outdated": "#fab219", "None": "#b9b8b0"}, "Year score"),
             ("source_score", ["Primary", "Secondary", "Misattributed", "None"],
              {"Primary": "#0ca30c", "Secondary": "#fab219", "Misattributed": "#d03b3b",
               "None": "#b9b8b0"}, "Source score")]
    for ax, (col, order, cmap, title) in zip(axes, specs):
        sub = s[s[col] != ""]
        sh = sub.groupby("model")[col].value_counts(normalize=True).unstack(fill_value=0) \
            .reindex(columns=order, fill_value=0)
        left = np.zeros(len(sh))
        for lab in order:
            v = sh[lab].values
            ax.barh(range(len(sh)), v, left=left, color=cmap[lab], label=lab, height=0.6,
                    edgecolor=SURFACE, linewidth=1.5)
            for i, x in enumerate(v):
                if x >= 0.08:
                    ax.text(left[i] + x / 2, i, f"{x:.0%}", ha="center", va="center", fontsize=8,
                            color="white" if lab in ("Latest", "Primary", "Misattributed") else INK)
            left += v
        ax.set_yticks(range(len(sh)), sh.index)
        ax.set_xlim(0, 1)
        pct_axis(ax, "x")
        ax.grid(axis="y", visible=False)
        ax.set_title(title, fontsize=10)
        ax.legend(ncol=4, loc="upper left", bbox_to_anchor=(0, -0.14), fontsize=8)
    fig.tight_layout()
    return save(fig, out, "09_year_and_source_scores"), ""


def chart_links(df, results_path, out):
    lc_path = Path(results_path).parent / "link_check.csv"
    if not lc_path.exists():
        return None, ("Link check not run. Run with --check-links (needs internet) "
                      "or `python pipeline/checks.py links <results.csv>`.")
    lc = pd.read_csv(lc_path, dtype=str, keep_default_na=False)
    if lc.empty:
        return None, "No links were cited in this file."
    order = ["ok", "blocked", "error", "broken", "no_such_site"]
    cmap = {"ok": "#0ca30c", "blocked": "#b9b8b0", "error": "#8a8980", "broken": "#d03b3b",
            "no_such_site": "#7a1f1f"}
    sh = lc.groupby("model")["status"].value_counts().unstack(fill_value=0) \
        .reindex(columns=order, fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 0.55 * len(sh) + 1.8))
    left = np.zeros(len(sh))
    for lab in order:
        v = sh[lab].values
        ax.barh(range(len(sh)), v, left=left, color=cmap[lab], label=lab.replace("_", " "),
                height=0.6, edgecolor=SURFACE, linewidth=1.5)
        left += v
    ax.set_yticks(range(len(sh)), sh.index)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Number of cited links")
    ax.set_title("Do the cited links exist?")
    ax.legend(ncol=5, loc="upper left", bbox_to_anchor=(0, -0.2), fontsize=8)
    return save(fig, out, "10_link_check"), ""


# ------------------------------------------------------------------ run log + summary

def update_run_log(df, results_path, run_name):
    log_path = REPO_ROOT / "results" / "run_log.csv"
    row = {
        "run": run_name,
        "results_file": str(Path(results_path).resolve().relative_to(REPO_ROOT))
        if Path(results_path).resolve().is_relative_to(REPO_ROOT) else str(results_path),
        "logged_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "answers": len(df),
        "models": df["model"].nunique(),
        "input_tokens": int(df["input_tokens"].fillna(0).sum()),
        "output_tokens": int(df["output_tokens"].fillna(0).sum()),
        "total_tokens": int(df["total_tokens"].fillna(0).sum()),
        "cost_usd": round(float(df["cost"].fillna(0).sum()), 6),
        "tokens_recorded": bool(df["input_tokens"].notna().any()),
    }
    log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame(columns=list(row))
    log = log[log["results_file"] != row["results_file"]]
    log = pd.concat([log, pd.DataFrame([row])], ignore_index=True)
    log.to_csv(log_path, index=False, lineterminator="\n")
    return log


def summary_table(df):
    s = df[df.scored]
    g = df.groupby("model", sort=False).agg(
        answers=("id", "size"), avg_tokens=("total_tokens", "mean"), avg_cost=("cost", "mean"),
        total_cost=("cost", lambda c: c.sum(min_count=1)), caveat_score=("caveat_score", "mean"))
    if not s.empty:
        a = s.groupby("model").agg(scored=("id", "size"), correct=("correct", "mean"),
                                   correct_or_close=("correct_or_close", "mean"))
        g = g.join(a)
        a2 = s.groupby("model").agg(n_correct=("correct", "sum"),
                                    scored_cost=("cost", lambda c: c.sum(min_count=1)))
        g = g.join(a2).join(cost_per_correct(df))
    lines = ["| model | answers | scored | % Correct | % Correct or Close | caveat elements (of 4) "
             "| avg tokens | avg cost | total cost | cost per correct answer |", "|" + "---|" * 10]
    for m, r in g.iterrows():
        def f(v, fmt):
            return "" if pd.isna(v) else fmt.format(v)
        cpc = f(r.get("cost_per_correct"), "${:.4f}")
        if not cpc and r.get("n_correct") == 0 and pd.notna(r.get("scored_cost")):
            cpc = "no correct answers"
        lines.append(f"| {m} | {int(r.answers)} | {f(r.get('scored'), '{:.0f}')} | "
                     f"{f(r.get('correct'), '{:.0%}')} | {f(r.get('correct_or_close'), '{:.0%}')} | "
                     f"{f(r.caveat_score, '{:.1f}')} | {f(r.avg_tokens, '{:,.0f}')} | "
                     f"{f(r.avg_cost, '${:.4f}')} | {f(r.total_cost, '${:.3f}')} | {cpc} |")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("results", help="results CSV in the shared columns")
    ap.add_argument("--check-links", action="store_true", help="test cited links (needs internet)")
    ap.add_argument("--no-log", action="store_true", help="don't add this file to results/run_log.csv")
    args = ap.parse_args()

    path = Path(args.results)
    run_name = path.parent.name if path.parent.name != "results" else path.stem
    out = path.parent / "report"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()

    df = load(path)
    if args.check_links:
        check_links_in_results(path)

    charts = [
        ("Accuracy by model", chart_accuracy_by_model(df, out)),
        ("Cost by model", chart_cost_by_model(df, out)),
        ("Accuracy vs. cost", chart_accuracy_vs_cost(df, out)),
        ("Accuracy by question type", chart_question_type(df, out)),
        ("Thinking and web search on vs. off", chart_on_off(df, out)),
        ("Skill vs. cold vs. MCP", chart_modes(df, out)),
        ("Haiku 4.5 vs. 5.5", chart_haiku(df, out)),
        ("Caveat check", chart_caveats(df, out)),
        ("Year and source scores", chart_year_source(df, out)),
        ("Link check", chart_links(df, path, out)),
    ]

    is_mock = run_name.lower() == "mock"
    log = None if (args.no_log or is_mock) else update_run_log(df, path, run_name)

    md = [f"# Report: {run_name}", "",
          f"Made {dt.datetime.now():%Y-%m-%d %H:%M} from `{path}` "
          f"({len(df)} answers, {int(df.scored.sum())} scored).", ""]
    if is_mock:
        md += ["> **MOCK DATA.** Every number here is invented. Use it only to test the charts.", ""]
    md += ["## By model", "", summary_table(df), "",
           "% Correct counts only scored answers. Caveat elements = how many of estimate/range, "
           "year, source and definition the automatic check found (see `pipeline/checks.py`). "
           "Cost per correct answer = total cost of the scored answers / number scored Correct "
           "(tool results such as web search and MCP add tokens, so this is the fair cost "
           "comparison).", "",
           "## Charts", ""]
    for title, (p, note) in charts:
        if p:
            md.append(f"### {title}\n\n![{title}]({p.name})" + (f"\n\n_{note}_" if note else "") + "\n")
        else:
            md.append(f"### {title}\n\n_Skipped: {note}_\n")
    if log is not None:
        md += ["## Running token and cost log (all runs)", "",
               f"Total so far: {int(log['total_tokens'].sum()):,} tokens, "
               f"${log['cost_usd'].sum():.4f} across {len(log)} runs. "
               "Full log: `results/run_log.csv`.", ""]
    (out / "summary.md").write_text("\n".join(md), encoding="utf-8")

    made = sum(1 for _, (p, _) in charts if p)
    print(f"{made} charts + summary.md written to {out}")
    for title, (p, note) in charts:
        if not p:
            print(f"  skipped {title}: {note}")
    if log is not None:
        print(f"Run log updated: {int(log['total_tokens'].sum()):,} tokens, "
              f"${log['cost_usd'].sum():.4f} total across {len(log)} runs")


if __name__ == "__main__":
    main()
