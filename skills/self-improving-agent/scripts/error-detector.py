#!/usr/bin/env python3
import os
import sys

ERROR_PATTERNS = [
    "error:", "Error:", "ERROR:",
    "failed", "FAILED",
    "command not found", "No such file",
    "Permission denied", "fatal:",
    "Exception", "Traceback",
    "npm ERR!", "ModuleNotFoundError",
    "SyntaxError", "TypeError",
    "exit code", "non-zero",
    "Exited with non-zero", "execution failed"
]

def check_error(output):
    output_upper = output.upper()
    for pattern in ERROR_PATTERNS:
        if pattern.upper() in output_upper or pattern in output:
            return True
    return False

def main():
    tool_output = os.environ.get("CLAUDE_TOOL_OUTPUT", "")

    if check_error(tool_output):
        print('''\n<error-detected>
A command error was detected. Consider logging this to .learnings/ERRORS.md if:
- The error was unexpected or non-obvious
- It required investigation to resolve
- It might recur in similar contexts
- The solution could benefit future sessions

Use the self-improvement skill format: [ERR-YYYYMMDD-XXX]
</error-detected>''')

if __name__ == "__main__":
    main()
