import ast, glob, collections

def lits(node):
    """Extract string literals from a str / list / dict outputs= or inputs= value."""
    out = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append(node.value)
    elif isinstance(node, (ast.List, ast.Tuple)):
        for e in node.elts:
            out += lits(e)
    elif isinstance(node, ast.Dict):
        for v in node.values:
            out += lits(v)
    return out

producers = collections.defaultdict(list)   # dataset -> [pipeline_file]
all_nodes = []  # (pipeline, output_set, input_set)

for f in sorted(glob.glob("src/crispy_kedro/pipelines/*/pipeline.py")):
    pname = f.split("/")[-2]
    tree = ast.parse(open(f).read())
    for call in ast.walk(tree):
        if isinstance(call, ast.Call):
            fn = call.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name != "node":
                continue
            outs, ins = [], []
            for kw in call.keywords:
                if kw.arg == "outputs":
                    outs = lits(kw.value)
                if kw.arg == "inputs":
                    ins = lits(kw.value)
            # positional inputs/outputs (node(func, inputs, outputs))
            for o in outs:
                producers[o].append(pname)
            all_nodes.append((pname, set(outs), set(ins)))

print("=== DATASETS PRODUCED BY MORE THAN ONE NODE (would crash sum()) ===")
dupes = {d: p for d, p in producers.items() if len(p) > 1}
if not dupes:
    print("  (none)")
for d, p in dupes.items():
    print(f"  {d!r}  produced by: {p}")

print()
print(f"total node() calls parsed: {len(all_nodes)}; distinct produced datasets: {len(producers)}")
