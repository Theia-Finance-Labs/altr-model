"""Build the ALTR methodology deck (.pptx) from structured slide data.

Black text on white, fuller standalone slides, internal/technical depth.
Formulae are pre-rendered PNGs (see render_formulas.py) placed as pictures —
PowerPoint has no LaTeX engine.

Run:  .venv/bin/python control/src/build_deck.py
Output: control/ALTR_Asset-Level_Transition_Risk_Methodology_v1.pptx

Fidelity rules enforced in the content (see paper_digest.md / vault_digest.md):
  - "ALTR"/"TRISK" are our labels for the paper's asset-level vs company-level models.
  - Part A (slides 1-4) = the published paper ONLY: AIM/CGE 2.2, no numeric rate, paper results.
  - Part B/C (5-14) = current crispy-kedro code (feat/altr-npv-fixes): MCPR, ramp, spreads, TV.
  - Bolton & Kacperczyk (2021) = equity carbon premium, adapted to the discount rate (flagged).
"""
import os

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR, MSO_AUTO_SIZE

HERE = os.path.dirname(os.path.abspath(__file__))
FIG = os.path.join(HERE, "..", "figures")
OUT = os.path.join(HERE, "..", "ALTR_Asset-Level_Transition_Risk_Methodology_v1.pptx")

FONT = "Arial"
BLACK = RGBColor(0x00, 0x00, 0x00)
GRAY = RGBColor(0x66, 0x66, 0x66)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

SW, SH = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.62)
CONTENT_W = SW - 2 * MARGIN


# ----------------------------------------------------------------------------- helpers
def _set_white_bg(slide):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = WHITE


def _txbox(slide, left, top, width, height):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE  # pin geometry; SHAPE_TO_FIT_TEXT lets renderers reposition boxes
    return box, tf


def _style_run(run, size, bold=False, italic=False, color=BLACK):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color


def add_title(slide, text):
    box, tf = _txbox(slide, MARGIN, Inches(0.34), CONTENT_W, Inches(0.9))
    p = tf.paragraphs[0]
    _style_run(p.add_run(), 1)  # placeholder to set defaults
    p.runs[0].text = text
    _style_run(p.runs[0], 27, bold=True)
    # thin rule under the title
    line = slide.shapes.add_connector(2, MARGIN, Inches(1.18), MARGIN + CONTENT_W, Inches(1.18))
    line.line.color.rgb = BLACK
    line.line.width = Pt(1.25)
    return Inches(1.30)


def add_message(slide, text, top=Inches(1.30)):
    box, tf = _txbox(slide, MARGIN, top, CONTENT_W, Inches(0.7))
    p = tf.paragraphs[0]
    r = p.add_run()
    r.text = text
    _style_run(r, 15.5, italic=True)
    return top + Inches(0.78)


def add_bullets(slide, items, top, left=None, width=None, size=13.5, gap=6):
    """items: list of str (plain paragraph) or (level, str)."""
    left = left or MARGIN
    width = width or CONTENT_W
    box, tf = _txbox(slide, left, top, width, SH - top - Inches(0.6))
    first = True
    for it in items:
        level, text = it if isinstance(it, tuple) else (0, it)
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.level = level
        p.space_after = Pt(gap)
        r = p.add_run()
        r.text = ("•  " if level == 0 else "–  ") + text if level <= 1 else text
        _style_run(r, size)
    return box


def add_formula(slide, name, top, width_in, left=None, label=None):
    left = left if left is not None else MARGIN
    max_w = SW - MARGIN - left  # never run past the right margin
    w = min(Inches(width_in), max_w)
    if label:
        box, tf = _txbox(slide, left, top, max_w, Inches(0.3))
        r = tf.paragraphs[0].add_run()
        r.text = label
        _style_run(r, 11.5, bold=True, color=GRAY)
        top = top + Inches(0.30)
    pic = slide.shapes.add_picture(os.path.join(FIG, f"{name}.png"), left, top, width=w)
    return top + Emu(pic.height) + Inches(0.12)


def add_source(slide, text):
    box, tf = _txbox(slide, MARGIN, Inches(7.04), CONTENT_W, Inches(0.36))
    r = tf.paragraphs[0].add_run()
    r.text = "Source: " + text
    _style_run(r, 8.5, italic=True, color=GRAY)


def add_notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def add_table(slide, rows, top, col_widths, size=10.5, header_bold=True):
    n_rows, n_cols = len(rows), len(rows[0])
    total_w = sum(col_widths)
    tbl_shape = slide.shapes.add_table(n_rows, n_cols, MARGIN, top, Inches(total_w), Inches(0.4 * n_rows))
    table = tbl_shape.table
    for j, w in enumerate(col_widths):
        table.columns[j].width = Inches(w)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = table.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = WHITE
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.08)
            cell.margin_top = Inches(0.02)
            cell.margin_bottom = Inches(0.02)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame
            tf.word_wrap = True
            p = tf.paragraphs[0]
            r = p.add_run()
            r.text = val
            _style_run(r, size, bold=(i == 0 and header_bold))
    return tbl_shape


def new_slide(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _set_white_bg(slide)
    return slide


# ----------------------------------------------------------------------------- build
def build():
    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH

    # ---- Slide 1: Title ----
    s = new_slide(prs)
    box, tf = _txbox(s, MARGIN, Inches(2.35), CONTENT_W, Inches(1.6))
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    r = tf.paragraphs[0].add_run()
    r.text = "Asset-Level Transition Risk (ALTR)"
    _style_run(r, 40, bold=True)
    p = tf.add_paragraph()
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = "Methodology of the published model, and the upgrades that\ngeneralize it across the full climate-scenario set"
    _style_run(r, 18)
    box2, tf2 = _txbox(s, MARGIN, Inches(4.5), CONTENT_W, Inches(1.2))
    for t, sz in [
        ("Internal methodology review · June 2026", 13),
        ("Model: crispy-kedro · branch feat/altr-npv-fixes", 11),
        ("Paper: Tang, Yilmaz, Gallice, Hejazi, Cervenka, Apeaning, Oweyssi, Kamboj, Buller", 11),
    ]:
        pp = tf2.add_paragraph() if tf2.paragraphs[0].runs else tf2.paragraphs[0]
        pp.alignment = PP_ALIGN.CENTER
        rr = pp.add_run()
        rr.text = t
        _style_run(rr, sz, color=GRAY if sz == 11 else BLACK)
    add_notes(s, "This deck has two halves. Slides 2-4: the model exactly as published in the paper. "
                 "Slides 5-14: the upgrades we pushed in crispy-kedro to make it run across every AR6 "
                 "scenario and to fix the NPV-direction error. 'ALTR' and 'TRISK' are our shorthand; the "
                 "paper itself says 'asset-level vs company-level'.")

    # ---- Slide 2: What the model does ----
    s = new_slide(prs)
    top = add_title(s, "What the model does")
    top = add_message(s, "It downscales global climate scenarios to individual power assets and re-values the firms that own them.")
    add_bullets(s, [
        "The firm is built bottom-up as the sum of the physical generation assets it owns — each with a location, capacity, age, and emissions factor.",
        "IPCC AR6 scenario trajectories (production, technology costs, carbon tax) are applied at the asset level, aggregated to firm free cash flow, and discounted to a net present value.",
        "The output is a value-at-risk: the change in a firm’s NPV between a below-2°C shock and a current-policies baseline.",
        "Headline: asset-level data puts the estimated cost of transition about 7% lower than a company-level stress test that ignores asset age and firm strategy.",
        "Label note: “ALTR” / “TRISK” here name the paper’s asset-level (bottom-up) model and the company-level (top-down) benchmark it is compared against.",
    ], top, width=Inches(6.8), size=14)
    add_formula(s, "eq15_var", Inches(4.7), 4.6, left=Inches(8.1), label="Value-at-risk (eq 15)")
    add_source(s, "Tang, Yilmaz, Gallice, Hejazi, Cervenka et al., “Asset-level analysis of corporate value adjustment in the climate transition” (abstract, §1).")
    add_notes(s, "VaR is a valuation change, not a market-risk VaR. The 7% is the abstract figure; under different "
                 "baseline constructions the paper also reports 8.6% (~$1.1T) and 4.1% (~$0.5T) — keep them separate.")

    # ---- Slide 3: ALTR vs TRISK ----
    s = new_slide(prs)
    top = add_title(s, "ALTR vs TRISK: what asset-level granularity changes")
    top = add_message(s, "Same scenario inputs; a more granular firm that retires its assets dynamically.")
    rows = [
        ["", "Company-level (TRISK-style)", "Asset-level (ALTR)"],
        ["Firm", "Static sector / country capacity", "Bottom-up sum of owned assets (location, age, EF)"],
        ["Profitability", "Revenue / production drawdown", "Full EBITDA: price − fuel − carbon − FOM"],
        ["Costs", "Aggregate or absent", "Technology-specific fuel, O&M, CapEx, emissions"],
        ["Retirement", "Uniform shock on fixed capacity", "Staggered by asset age; older first; no forced stranding"],
        ["Capacity & cost", "Held constant to 2050", "Fall as assets retire"],
        ["Horizon inputs", "Transition starts at the shock", "5-year forward plans; captures overshoot"],
        ["Comparability", "Sector aggregate", "Firm vs peers under a shared carbon budget"],
    ]
    add_table(s, rows, top, col_widths=[1.7, 4.7, 5.7], size=11)
    add_bullets(s, [
        "Net effect: asset-level features lower estimated loss — ~7% (abstract), 8.6% / ~$1.1T (common baseline), 4.1% / ~$0.5T (separate baselines), reported separately.",
        "Caveat from the paper: more granularity does not always lower loss — 5-year forward plans add overshoot and can raise it.",
    ], Inches(5.55), size=12)
    add_source(s, "Paper §3 and §5. The paper frames this as “asset-level vs company-level”; TRISK is the company-level methodology of its institutional home (1in1000 / Theia Finance Labs).")
    add_notes(s, "Fact-check guard: the paper never writes 'ALTR' or 'TRISK', and has no 4-bucket alignment scheme "
                 "(it uses a continuous market-share mechanism plus aligned/misaligned). Present the table as the "
                 "paper's asset- vs company-level differences.")

    # ---- Slide 4: The valuation engine ----
    s = new_slide(prs)
    top = add_title(s, "The valuation engine")
    top = add_message(s, "Asset cash flows are built from an EBITDA decomposition, summed to the firm, and discounted with a dividend-discount terminal value.")
    add_bullets(s, [
        "Downscale: scenario production → asset by market share η (eq 2); output Q = capacity × capacity factor (eq 3).",
        "EBITDA per asset (eq 7): price minus fuel, carbon, and FOM. The carbon price enters here, as emissions factor × carbon tax × (1 − free allocation).",
        "Firm free cash flow (eq 9): sum of asset EBITDA minus CapEx, with a 10% scrap recovery on retired capacity (eq 8).",
        "NPV (eq 10): discounted FCFF plus a Gordon-growth terminal value. A single rate r, with only the condition r > g — the paper sets no number.",
        "Staggered retirement (eq 13): a logistic function loads more of the production shock onto older plants, avoiding forced stranding.",
    ], top, width=Inches(6.3), size=12.5)
    fy = Inches(1.95)
    fy = add_formula(s, "eq07_ebitda", fy, 5.6, left=Inches(7.4), label="EBITDA per asset (eq 7) — carbon enters here")
    fy = add_formula(s, "eq09_fcff", fy, 4.0, left=Inches(7.4), label="Firm free cash flow (eq 9)")
    fy = add_formula(s, "eq10_npv", fy, 5.3, left=Inches(7.4), label="NPV with terminal value (eq 10)")
    add_source(s, "Paper §2 (equations 2–15). Equations transcribed to a clean form; the paper prints two different equations as “(2)” and gives no numeric discount rate.")
    add_notes(s, "The EBITDA decomposition (eq 7) is the heart of the model and the main departure from a revenue-only "
                 "DCF. Do not state a WACC — the paper specifies none.")

    # ---- Slide 5: Why upgrade (bridge) ----
    s = new_slide(prs)
    top = add_title(s, "Why upgrade: one scenario → all scenarios, and the NPV paradox")
    top = add_message(s, "The published model was calibrated on one IAM. Generalizing it across the AR6 set exposed a sign error in the transition signal.")
    add_bullets(s, [
        "The paper runs on a single IAM (AIM/CGE 2.2). Production needs the model to work across the full AR6 provider set — WITCH, REMIND, MESSAGEix, GCAM, IMAGE, COFFEE, TIAM, and more.",
        "Running it broadly surfaced the NPV paradox: about 16% of technology–geography combinations showed fossil firms gaining value under the transition shock — the wrong direction.",
        "The cause is not one bug but five interacting distortions:",
        (1, "near-term price windfall from a hard baseline→target switch;"),
        (1, "gas free-riding on the marginal-generator position;"),
        (1, "terminal value dominating the NPV (~20× final-year cash flow);"),
        (1, "a single discount rate that cannot separate brown from green;"),
        (1, "static renewable capture prices."),
        "The next five slides each fix one distortion. Together they pull the transition signal back toward the expected direction in the large majority of cases — quantified on slide 11.",
    ], top, width=Inches(11.6), size=13)
    add_source(s, "ALTR Improvement Brief and NPV Direction-Fix Research (crispy-kedro/docs/research, ALTR_NPV_Direction_Fix_Research.md).")
    add_notes(s, "This is the bridge slide: it motivates the five methodology fixes. The 16% paradox figure and the "
                 "'five interacting distortions' framing come from the improvement brief.")

    # ---- Slide 6: MCPR ----
    s = new_slide(prs)
    top = add_title(s, "Marginal Cost Price Ratio (MCPR) pricing")
    top = add_message(s, "IAM electricity prices are technology-specific costs, not the uniform market price generators actually receive.")
    add_bullets(s, [
        "In a merit-order market every generator is paid the clearing price set by the marginal dispatchable plant — usually gas. Low-cost renewables earn that same price: the infra-marginal rent that keeps them viable.",
        "IAM prices instead approximate each technology’s own LCOE. Solar can sit above the clearing price; hydro far below it.",
        "MCPR sets one clearing price from the marginal technologies, then applies empirical capture (value) factors for variable renewables (Hirth 2013): about 0.85 for solar, 0.90 for wind.",
        "Worked example (AIM/CGE 2.2, Asia): solar $119 → $71 (×0.85); hydro $53 → $83, now earning the full clearing price.",
    ], top, width=Inches(7.0), size=13.5)
    add_formula(s, "u_mcpr_market", Inches(4.95), 5.0, left=Inches(7.7), label="Clearing price from marginal techs")
    add_formula(s, "u_mcpr_adj", Inches(5.95), 4.6, left=Inches(7.7), label="Capture-adjusted price per technology")
    add_source(s, "ALTR MCPR methodology (MCPR/ALTR_MCPR_methodology_v1.md); Hirth (2013); Koolen et al. (2023, JRC).")
    add_notes(s, "MCPR is the conceptual spine of the upgrade: the differential carbon cost, gas treatment, and price "
                 "ramp all build on the merit-order clearing-price idea. Value factors are insensitive across 0.55–1.0 in sensitivity tests.")

    # ---- Slide 7: Carbon treatment + scenario generalization ----
    s = new_slide(prs)
    top = add_title(s, "Carbon-price treatment, made scenario-agnostic")
    top = add_message(s, "Carbon enters as a differential cost above the marginal generator — and the model auto-detects how each IAM already prices carbon.")
    add_bullets(s, [
        "Carbon cost is charged on a plant’s emissions above the marginal generator’s, not its absolute emissions — the clearing price already embeds the marginal plant’s carbon.",
        "The marginal emissions factor falls as renewables grow (quadratic in VRE share). As the grid cleans, every fossil plant’s differential carbon cost rises.",
        "IAMs differ in whether the electricity price already contains carbon. MCPR v2 auto-detects this: above 50% carbon-price coverage it uses carbon_explicit (full emissions factor); otherwise merit_order_decline (differential).",
        "Effect: carbon is neither double-counted (for IAMs that embed it) nor missed (for those that report it separately) — the same firm is priced consistently whatever the scenario.",
    ], top, width=Inches(7.0), size=13)
    add_formula(s, "u_carbon_diff", Inches(4.95), 5.2, left=Inches(7.7), label="Differential carbon cost")
    add_formula(s, "u_dyn_ef", Inches(5.95), 4.6, left=Inches(7.7), label="Marginal EF declines with VRE share")
    add_source(s, "crispy-kedro commits 056d1f6, 49efb56; MCPR v2 spec (docs/superpowers/specs/2026-04-14-mcpr-v2-redesign.md).")
    add_notes(s, "This is the slide that makes the model 'work on the full set of scenarios'. The >50% coverage "
                 "threshold and the two named modes (carbon_explicit / merit_order_decline) are the auto-detection logic.")

    # ---- Slide 8: Price ramp (RC4) ----
    s = new_slide(prs)
    top = add_title(s, "Smoothing the transition: the price ramp (RC4)")
    top = add_message(s, "A hard baseline→target price switch at the shock year created a near-term windfall that flipped NPV signs.")
    add_bullets(s, [
        "The mixed scenario surface switched from baseline to target prices instantly at the shock year. Target prices are higher near-term (carbon raises the still-fossil system’s clearing price) and lower later (renewables dominate).",
        "With production falling but price jumping, fossil firms booked a near-term revenue windfall that, discounted at 7%, outweighed the long-run decline — a direct driver of the paradox.",
        "Fix: linearly blend baseline into target over the shock window, matching the gradual production ramp. The discontinuous windfall disappears and the signal turns negative for fossils.",
    ], top, width=Inches(7.1), size=13.5)
    add_formula(s, "u_price_ramp", Inches(5.1), 5.2, left=Inches(7.8), label="Linear price blend over the shock window")
    add_source(s, "ALTR Improvement Brief (RC4); crispy-kedro commit 056d1f6 (earnings_model price ramp).")
    add_notes(s, "Conceptually clean: a firm that transitions gradually should face gradually transitioning prices. "
                 "β ramps 0→1 from the shock year S to the alignment year S*.")

    # ---- Slide 9: Discount rates ----
    s = new_slide(prs)
    top = add_title(s, "Technology-differentiated discount rates")
    top = add_message(s, "Brown and green assets no longer share one discount rate.")
    add_bullets(s, [
        "The published model uses a single rate r (it sets no value; the code uses 7%). One rate discounts every cash flow equally — raising it penalizes renewables as much as fossils, so it cannot create the transition signal.",
        "The upgrade adds a carbon premium: brown technologies +100 bps, green −50 bps. Higher rates compress fossil valuations; lower rates lift renewables.",
        "Rationale: Bolton & Kacperczyk (2021) document a carbon premium in equity returns. We adapt it to the discount rate as a financing-cost spread — an adaptation, not a direct port (their premium is measured on equity).",
    ], top, width=Inches(7.1), size=13.5)
    add_formula(s, "u_discount", Inches(4.95), 5.4, left=Inches(7.8), label="Brown / green discount spreads")
    add_source(s, "crispy-kedro commit 056d1f6 (valuation_model; brown +100 bps / green −50 bps); Bolton & Kacperczyk (2021).")
    add_notes(s, "Flag honestly: Bolton & Kacperczyk is an equity carbon premium; applying it to the discount rate is "
                 "our adaptation. The parameter sweep showed asymmetric discounting alone does not fix the narrative — it works with the cost-structure fixes, not instead of them.")

    # ---- Slide 10: Terminal value ----
    s = new_slide(prs)
    top = add_title(s, "Stranding-aware terminal value")
    top = add_message(s, "A perpetuity on the final year’s cash flow overvalues firms whose assets are being stranded.")
    add_bullets(s, [
        "In eq 10 the Gordon-growth terminal value can reach roughly 20× the final-year FCFF — so a stressed final year is amplified, not dampened.",
        "First change: normalize the terminal FCFF over a 3-year window (Damodaran / McKinsey) so one noisy year does not set the perpetuity.",
        "Second change: a three-tier stranding-aware rule (Gourdel 2024). An asset declining to zero gets no perpetuity; a stressed-but-surviving asset gets a capped one; a healthy asset gets the standard formula.",
        "Terminal growth is split by technology: brown 0%, green 2%.",
    ], top, width=Inches(7.1), size=13.5)
    add_formula(s, "u_tv_strand", Inches(5.1), 5.4, left=Inches(7.8), label="Normalized, gated terminal value")
    add_source(s, "crispy-kedro commit 056d1f6 (valuation_model, 3-tier TV); Gourdel (2024).")
    add_notes(s, "Terminal-value domination was one of the five distortions: without this, the perpetuity dwarfs the "
                 "explicit-horizon cash flows and washes out the transition signal.")

    # ---- Slide 11: Results across scenarios ----
    s = new_slide(prs)
    top = add_title(s, "Results across the full scenario set")
    top = add_message(s, "The model now runs clean across the AR6 IAM set, and the carbon treatment adapts per scenario.")
    add_bullets(s, [
        "Key per-scenario difference is carbon treatment. IAMs that report a carbon price trigger carbon_explicit / full emissions factor; IAMs that embed carbon in the electricity price trigger merit_order_decline / differential — auto-detected per scenario, so the same firm is priced consistently whatever the IAM.",
        "The MCPR v2 correction is validated on 5 IAM providers (COFFEE, GCAM, IMAGE, MESSAGEix, WITCH) × 3 configs — 15 of 15 runs pass. The earlier April comparison campaign spanned 25+ IAM versions across the AR6 set (AIM/CGE, the REMIND family, TIAM, GEM-E3, and others).",
        "Direction after the fixes (feat/altr-npv-fixes, commit 056d1f6): carbontech ~78.5% value-destroying (was 52.3%), greentech ~85.6% value-creating (was 33.3%). Residual wrong-direction cases remain — gas is the least-negative fossil and the borderline case.",
    ], top, width=Inches(7.1), size=12.5)
    add_formula(s, "u_merit_decline", Inches(5.25), 5.0, left=Inches(7.8), label="Merit-order decline mode (MCPR v2)")
    add_source(s, "MCPR v2 batch: workspace/batch_run_mcpr_v2.log (5 providers × 3 configs, 15/15 PASS); broader coverage: workspace/comparison_results/ (25+ IAM versions, April 2026); direction: commit 056d1f6. NPV magnitudes vary across the model’s evolution — stated directionally and version-stamped.")
    add_notes(s, "Leads on the carbon-treatment-per-scenario logic (well-grounded). Coverage is split honestly: the "
                 "MCPR v2 correction was validated on 5 providers (15/15); the broader 25+ IAM coverage is from the earlier "
                 "April comparison campaign. Direction numbers (78.5% / 85.6%) are from commit 056d1f6; residual paradox "
                 "cases remain — gas is the honest open item.")

    # ---- Slide 12: Ways forward I ----
    s = new_slide(prs)
    top = add_title(s, "Ways forward (1): from value-at-risk to default risk")
    top = add_message(s, "The model stops at NPV. A structural credit layer would turn valuation shocks into probabilities of default.")
    add_bullets(s, [
        "A Merton structural model treats equity as a call option on firm assets; the transition-driven fall in asset value raises the distance-to-default and the implied PD.",
        "Building blocks from the literature: Reinders (closed-form NPV→PD), Cormack (time-dependent drift, rating-dependent volatility), Gourdel (a carbon-premium feedback between PD and borrowing cost), and CRISK (market-implied, continuous monitoring).",
        "This is the direction supervisors are moving: the EBA’s 2025 climate stress-test guidelines (EBA/GL/2025/04) make climate stress testing with capital-adequacy effects mandatory from 2026 — PD is one transmission route.",
    ], top, width=Inches(7.1), size=13.5)
    add_formula(s, "w_merton", Inches(5.1), 5.6, left=Inches(7.8), label="Merton distance-to-default → PD")
    add_source(s, "ALTR Improvement Brief (M1): Reinders (2020), Cormack (2020), Gourdel (2024), Jung–Engle–Berner CRISK (2025); EBA/GL/2025/04.")
    add_notes(s, "When this is built, don't implement vanilla Merton — the brief is explicit that the climate-relevant "
                 "extensions (dynamic leverage, jump-diffusion tails, scenario-dependent volatility) should be in from the start.")

    # ---- Slide 13: Ways forward II ----
    s = new_slide(prs)
    top = add_title(s, "Ways forward (2): from one scenario to a distribution")
    top = add_message(s, "Replace single-scenario point estimates with a probability-weighted loss distribution.")
    add_bullets(s, [
        "Each run today is one deterministic scenario. A Monte Carlo layer would draw over the uncertain valuation parameters — discount rate, terminal growth, carbon price, pass-through — to produce a loss distribution and a true climate VaR.",
        "Scenarios themselves can be probability-weighted (Le Guenedal’s Bayesian updating), and asset correlations modelled with copulas so portfolio tail risk is not understated.",
        "Two further extensions: network contagion (Veraart) to propagate firm losses through the financial system, and a merit-order dispatch model computing capture prices from supply–demand clearing — which no published transition-risk model yet does.",
    ], top, width=Inches(7.1), size=13.5)
    add_formula(s, "w_prob_npv", Inches(5.2), 5.0, left=Inches(7.8), label="Probability-weighted expected NPV")
    add_source(s, "ALTR Improvement Brief (M5, M6, N1): Desnos et al. / Amundi, Le Guenedal (2022), Veraart (2020).")
    add_notes(s, "The merit-order dispatch model is flagged in the brief as the genuine academic contribution — the gap "
                 "where ALTR could lead rather than follow.")

    # ---- Slide 14: Summary + references ----
    s = new_slide(prs)
    top = add_title(s, "Summary")
    top = add_message(s, "A published asset-level model, generalized across the AR6 scenario set and corrected so the large majority of cases show the expected direction.")
    add_bullets(s, [
        "The paper’s contribution: bottom-up, asset-level valuation that lowers the estimated cost of transition by about 7% versus company-level stress tests.",
        "The upgrades: merit-order pricing, differential carbon with per-scenario auto-detection, a smoothed price ramp, technology-differentiated discount rates, and stranding-aware terminal value — together they move the transition signal back to the expected direction in the large majority of cases (carbontech ~78% negative, greentech ~86% positive), with residual cases remaining.",
        "Next: a credit-risk PD layer, and a probabilistic, multi-scenario value-at-risk.",
    ], top, size=14)
    add_bullets(s, [
        "Tang, Yilmaz, Gallice, Hejazi, Cervenka et al. — Asset-level analysis of corporate value adjustment in the climate transition.",
        "Hirth (2013); Koolen et al. (2023); Bolton & Kacperczyk (2021); Gourdel (2024); Reinders (2020); Cormack (2020).",
    ], Inches(5.5), size=10.5, gap=3)
    add_source(s, "Methodology sources: crispy-kedro docs/research and MCPR methodology; paper digest and vault digest in control/.")
    add_notes(s, "Close on the arc: published model → scenario-generalized, sign-corrected engine → credit + probabilistic next steps.")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    prs.save(OUT)
    print(f"Saved {len(prs.slides._sldIdLst)} slides -> {OUT}")


if __name__ == "__main__":
    build()
