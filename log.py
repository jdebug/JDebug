import sublime

import os
import sys

DEBUG = None

def set_log_level(log_level):
    global DEBUG
    
    DEBUG = log_level

def log_debug(line):
    """
    Write debug output, if enabled, to stdout (Sublime console)
    """
    global DEBUG
    if DEBUG:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
