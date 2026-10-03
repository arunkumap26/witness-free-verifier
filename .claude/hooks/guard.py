"""PostToolUse syntax gate. Catches the 3am spiral where a syntax error breaks the eval
and the agent starts "fixing" the eval instead of its own file.
Exit 2 sends stderr back to the model so it fixes the file immediately."""
import json
import py_compile
import sys

try:
    path = json.load(sys.stdin).get("tool_input", {}).get("file_path", "")
except ValueError:
    sys.exit(0)

try:
    if path.endswith(".py"):
        py_compile.compile(path, doraise=True)
    elif path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            json.load(f)
except (py_compile.PyCompileError, ValueError) as e:
    print(f"Syntax error introduced in {path}: {str(e)[:400]}", file=sys.stderr)
    sys.exit(2)
except OSError:
    pass
sys.exit(0)
