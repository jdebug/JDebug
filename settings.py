import sublime

import os
import sys


def get_setting(key, default=None, view=None):
    """
    Read setting value from JDebug settings file
    """
    try:
        if view is None:
            view = sublime.active_window().active_view()
        s = view.settings()
        if s.has("jdebug%s" % key):
            return s.get("jdebug%s" % key)
    except:
        pass
    return sublime.load_settings("JDebug.sublime-settings").get(key, default)