"""Render every deck equation to a tight, transparent, 300 DPI PNG via matplotlib mathtext.

Design constraint: PowerPoint has no LaTeX engine, so each formula is rendered
externally and placed as an image. matplotlib mathtext is a LaTeX *subset* — it does
NOT support \\begin{cases}/\\begin{array}, \\text{}, or \\mathbb{}. Every piecewise
equation below is reformulated into a mathtext-safe single line (clip(), indicators in
words) and words-in-math use \\mathrm{}.

Run:  .venv/bin/python control/src/render_formulas.py
"""
import os
import shutil
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = os.path.join(os.path.dirname(__file__), "..", "figures")
OUT = os.path.abspath(OUT)
os.makedirs(OUT, exist_ok=True)

# name -> (LaTeX body without the $ delimiters, font size)
FORMULAS = {
    # ---- Part A: the published paper model ----
    "eq02_downscale": (r"P^{\,i}_{h,a,s,t} = \eta_{a,i,h}\;\cdot\;P_{h,s,t}", 30),
    "eq03_output": (r"Q_{t,s,a} = PC_{t,s,a}\;\cdot\;CF_{t,s,a}", 32),
    "eq04_revenue": (r"R^{s,t}_{i} = \sum_{h \in H} Q_{t,s,a}\;\cdot\;p_{t,s}", 30),
    "eq05_fuel": (r"c_{t,s,a} = \frac{P^{F}_{t,s}}{\eta_{a,k}}", 32),
    "eq07_ebitda": (
        r"\Pi_{t,s,a} = Q_{t,s,a}\left(p_{t,s} - c_{t,s,a} - EF_k\,T_{t,s,a}(1-\phi)\right)"
        r" - \frac{FOM_{t,s,a}}{2}\,\Delta PC_{t,s,a}",
        26,
    ),
    "eq08_capex": (r"Capex_{t,s} = \left(A_{t,s} + R_{t,s} - \gamma\,X_{t,s}\right)\,C_{t,s,h}", 28),
    "eq09_fcff": (r"J_{t,s} = \sum_{a}\Pi_{t,s,a} \;-\; Capex_{t,s}", 30),
    "eq10_npv": (
        r"NPV_s = \sum_{t=1}^{T}\frac{J_{t,s}}{(1+r)^{t}} \;+\; \frac{J_{T,s}\,(1+g)}{r-g}",
        30,
    ),
    "eq13_stagger": (
        r"g(x, N_q) = 1 - \sum_{j=1}^{n}\frac{1}{2^{\,j}}"
        r"\left(\frac{1}{1+\exp\!\left(-k\,(x - a_j N_q)\right)}\right)",
        28,
    ),
    "eq15_var": (r"VaR^{NPV}_{i} = NPV^{\mathrm{stress}}_{i} - NPV^{\mathrm{baseline}}_{i}", 30),
    # ---- Part B: the upgrades ----
    "u_mcpr_market": (
        r"P_{\mathrm{market}}(g,t,s) = \max_{h \in D}\,P_{\mathrm{IAM}}(h,g,t,s)\,(1+\lambda)",
        28,
    ),
    "u_mcpr_adj": (r"P_{\mathrm{adj}}(h,g,t,s) = P_{\mathrm{market}}(g,t,s)\;\times\;VF(h)", 28),
    "u_carbon_diff": (
        r"c^{\mathrm{carbon}}_{t,s,a} = Q_{t,s,a}\,T_{t,s}\,\max\!\left(EF_h - EF_{\mathrm{marg}},\,0\right)(1-\phi)",
        26,
    ),
    "u_dyn_ef": (r"EF_{\mathrm{marg}}(t) = EF^{0}_{\mathrm{marg}}\,\left(1 - s_{\mathrm{VRE}}(t)\right)^{2}", 28),
    "u_price_ramp": (
        r"p_t = (1-\beta_t)\,p^{\mathrm{base}}_t + \beta_t\,p^{\mathrm{tgt}}_t,"
        r"\quad \beta_t = \mathrm{clip}\!\left(\frac{t-S}{S^{*}-S},\,0,\,1\right)",
        25,
    ),
    "u_discount": (
        r"r_{\mathrm{brown}} = r_0 + 100\,\mathrm{bps}"
        r"\qquad r_{\mathrm{green}} = r_0 - 50\,\mathrm{bps}",
        27,
    ),
    "u_merit_decline": (
        r"P_{\mathrm{market}}(t) = P^{0}_{\mathrm{market}}\,\max\!\left(1 - \alpha\,s_{\mathrm{VRE}}(t),\;\mathrm{floor}\right)",
        26,
    ),
    "u_tv_strand": (
        r"TV = \frac{\bar{J}_{T}\,(1+g)}{r-g},\quad \bar{J}_{T} = \mathrm{mean}\!\left(J_{T-2},J_{T-1},J_{T}\right)",
        26,
    ),
    # ---- Part C: ways forward ----
    "w_merton": (
        r"DD = \frac{\ln(V/D) + \left(\mu - \frac{1}{2}\sigma^{2}\right)\tau}{\sigma\sqrt{\tau}}"
        r"\qquad PD = N(-DD)",
        26,
    ),
    "w_prob_npv": (r"\mathrm{E}[NPV] = \sum_{s}\pi_s\;NPV_s \qquad \sum_{s}\pi_s = 1", 28),
}


def render(name, latex, fontsize):
    try:
        fig = plt.figure()
        fig.text(0.01, 0.5, f"${latex}$", fontsize=fontsize, va="center", ha="left", color="black")
        path = os.path.join(OUT, f"{name}.png")
        fig.savefig(path, dpi=300, bbox_inches="tight", pad_inches=0.08, transparent=True)
        plt.close(fig)
        return True, ""
    except Exception as e:  # noqa: BLE001 - smoke test wants every failure surfaced
        plt.close("all")
        return False, repr(e)


if __name__ == "__main__":
    print(f"pdflatex on PATH: {shutil.which('pdflatex')}")
    n_ok = 0
    for name, (latex, fs) in FORMULAS.items():
        ok, err = render(name, latex, fs)
        print(f"{'OK  ' if ok else 'FAIL'} {name}{'' if ok else ': ' + err}")
        n_ok += ok
    print(f"\n{n_ok}/{len(FORMULAS)} formulas rendered into {OUT}")
