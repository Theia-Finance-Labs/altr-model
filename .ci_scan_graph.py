import ast, glob, collections

def lits(node):
    out = []
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.append(node.value)
    elif isinstance(node, (ast.List, ast.Tuple)):
        for e in node.elts:
            out += lits(e)
    elif isinstance(node, ast.Dict):
        for v in node.values:
            out += lits(v)
    elif isinstance(node, ast.Call):
        # dict(a="x", b="y") form
        fname = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if fname == "dict":
            for kw in node.keywords:
                out += lits(kw.value)
    return out

nodes = []  # (pipeline, name, set(inputs_datasets), set(outputs))
producers = collections.defaultdict(set)

for f in sorted(glob.glob("src/crispy_kedro/pipelines/*/pipeline.py")):
    pname = f.split("/")[-2]
    tree = ast.parse(open(f).read())
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        fn = call.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if name != "node":
            continue
        outs, ins = [], []
        # positional args: node(func, inputs, outputs)
        for i, a in enumerate(call.args):
            if i == 1:
                ins = lits(a)
            elif i == 2:
                outs = lits(a)
        for kw in call.keywords:
            if kw.arg == "outputs":
                outs = lits(kw.value)
            if kw.arg == "inputs":
                ins = lits(kw.value)
        # drop params: edges (not real dataset dependencies)
        ins = [x for x in ins if not x.startswith("params:") and x != "parameters"]
        nodes.append((pname, name, set(ins), set(outs)))
        for o in outs:
            producers[o].add(pname)

# Build dataset graph: producer_dataset -> consumer datasets via node
# Node-level edge: input dataset -> output dataset
edges = collections.defaultdict(set)
for pname, name, ins, outs in nodes:
    for i in ins:
        for o in outs:
            edges[i].add(o)

# cycle detection (DFS) over dataset graph
WHITE, GRAY, BLACK = 0, 1, 2
color = collections.defaultdict(int)
cycle_path = []

def dfs(u, stack):
    color[u] = GRAY
    stack.append(u)
    for v in edges.get(u, ()):
        if color[v] == GRAY:
            idx = stack.index(v)
            cycle_path.extend(stack[idx:] + [v])
            return True
        if color[v] == WHITE and dfs(v, stack):
            return True
    stack.pop()
    color[u] = BLACK
    return False

found = False
allds = set(edges) | {d for vs in edges.values() for d in vs}
for d in allds:
    if color[d] == WHITE:
        if dfs(d, []):
            found = True
            break

print("=== DUPLICATE OUTPUTS (produced by >1 node -> sum() crash) ===")
# producers maps dataset -> set(pipelines); need per-node count
out_count = collections.Counter()
out_where = collections.defaultdict(list)
for pname, name, ins, outs in nodes:
    for o in outs:
        out_count[o] += 1
        out_where[o].append(f"{pname}/{name}")
dupes = {d: out_where[d] for d, c in out_count.items() if c > 1}
print("  DUPES:", dupes if dupes else "(none)")
print()

print("=== CYCLE in combined dataset graph? ===")
print("  CYCLE:", " -> ".join(cycle_path) if found else "(none)")

# free inputs: consumed but never produced by any node
consumed = set()
for _, _, ins, _ in nodes:
    consumed |= ins
produced = set(producers)
free = sorted(consumed - produced)
print()
print("=== FREE INPUTS (consumed, no node produces them -> must be in catalog) ===")
for d in free:
    print("  ", d)
