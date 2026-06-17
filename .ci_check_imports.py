import ast, glob

for pf in sorted(glob.glob("src/crispy_kedro/pipelines/*/pipeline.py")):
    pkg = pf.rsplit("/", 1)[0]
    nf = pkg + "/nodes.py"
    pname = pf.split("/")[-2]
    ptree = ast.parse(open(pf).read())
    # names imported "from .nodes import (...)"
    imported = []
    for n in ast.walk(ptree):
        if isinstance(n, ast.ImportFrom) and n.module and "nodes" in n.module:
            imported += [a.name for a in n.names]
    # names defined in nodes.py
    try:
        ntree = ast.parse(open(nf).read())
    except FileNotFoundError:
        print(f"[{pname}] NO nodes.py")
        continue
    defined = {n.name for n in ast.walk(ntree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    # also names referenced as node(func=NAME) or node(NAME, ...) in pipeline.py
    referenced = set()
    for call in ast.walk(ptree):
        if isinstance(call, ast.Call):
            fn = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
            if fn == "node":
                if call.args:
                    a0 = call.args[0]
                    if isinstance(a0, ast.Name):
                        referenced.add(a0.id)
                for kw in call.keywords:
                    if kw.arg == "func" and isinstance(kw.value, ast.Name):
                        referenced.add(kw.value.id)
    missing_import = [x for x in imported if x not in defined]
    missing_ref = [x for x in referenced if x not in defined and x not in imported]
    flag = "  <-- BROKEN" if (missing_import or missing_ref) else ""
    print(f"[{pname}] imported={len(imported)} defined={len(defined)} "
          f"missing_import={missing_import} missing_ref={missing_ref}{flag}")
