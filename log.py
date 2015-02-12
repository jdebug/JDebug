import sublime

import os
import sys

DEBUG = None

def log_debug(line):
    """
    Write debug output, if enabled, to stdout (Sublime console)
    """
    global DEBUG
    if DEBUG:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
