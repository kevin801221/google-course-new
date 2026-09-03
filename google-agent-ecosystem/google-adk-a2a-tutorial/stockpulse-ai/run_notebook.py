#!/usr/bin/env python
"""Execute a notebook end-to-end and report PASS/FAIL with the failing cell."""
import argparse, pathlib, sys
import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError, CellTimeoutError, DeadKernelError


def run(path, kernel="python3", timeout=600, out=None):
    path = pathlib.Path(path).resolve()
    nb = nbformat.read(path, as_version=4)
    client = NotebookClient(nb, kernel_name=kernel, timeout=timeout,
                            cwd=str(path.parent), allow_errors=False, record_timing=True)
    out = pathlib.Path(out) if out else path.with_suffix(".executed.ipynb")
    ok, err = False, None
    try:
        client.execute()
        ok = True
    except Exception as e:          # 包含 NoSuchKernel / 啟動失敗，不只 cell 執行錯誤
        err = e
    finally:
        nbformat.write(nb, out)     # 一定要寫，traceback 都在裡面

    # timing report
    times = []
    for i, c in enumerate(nb.cells):
        t = (c.get("metadata", {}).get("execution") or {})
        if t.get("shell.execute_reply") and t.get("execute_input"):
            import datetime as dt
            a = dt.datetime.fromisoformat(t["execute_input"].replace("Z", "+00:00"))
            b = dt.datetime.fromisoformat(t["shell.execute_reply"].replace("Z", "+00:00"))
            times.append((i, (b - a).total_seconds()))
    if times:
        total = sum(s for _, s in times)
        print(f"\n⏱  總執行時間 {total:.0f}s。最慢的 8 個 cell：")
        for i, s in sorted(times, key=lambda x: -x[1])[:8]:
            src = nb.cells[i].source.strip().splitlines()
            head = next((l for l in src if l.strip() and not l.strip().startswith("#")), src[0] if src else "")
            print(f"     cell {i:>3}  {s:>6.1f}s  {head[:64]}")

    if ok:
        print(f"\nPASS  {path.name}  ({len(nb.cells)} cells) -> {out.name}")
        return 0

    print(f"\nFAIL  {path.name} -> {out.name}\n")
    for i, cell in enumerate(nb.cells):
        tb = "\n".join(l for o in cell.get("outputs", []) if o.output_type == "error"
                       for l in o.get("traceback", []))
        if tb:
            print(f"--- 失敗的 cell index {i} ---")
            print(cell.source[:3000])
            print("--- traceback ---")
            print(tb[-4000:])
            break
    else:
        print(err)
    return 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("notebook"); p.add_argument("--kernel", default="python3")
    p.add_argument("--timeout", type=int, default=600); p.add_argument("--out")
    a = p.parse_args()
    sys.exit(run(a.notebook, a.kernel, a.timeout, a.out))
