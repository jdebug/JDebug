"""Copyright 2015 Senthil Jeganathan, 2012 Fredrik Ehnbom, 2014 Jason Gardner, 
This software is provided 'as-is', without any express or implied
waranty. In no event will the authors be held liable for any damages
arising from the use of this software.

Permission is granted to anyone to use this software for any purpose,
including commercial applications, and to alter it and redistribute it

   1. The origin of this software must not be misrepresented; you must not
   claim that you wrote the original software. If you use this software
   in a product, an acknowledgment in the product documentation would be
   appreciated but is not required.

   2. Altered source versions must be plainly marked as such, and must not be
   misrepresented as being the original software.

   3. This notice may not be removed or altered from any source
   distribution.
"""
import sublime
import sublime_plugin
import subprocess
import threading
import time
import traceback
import os
import sys
import re

try:
    import Queue
except:
    import queue as Queue

try:
    from .util import *
    from .log import *
except:
    try:
        from util import *
        from log import *
    except:
        from JDebug.util import *
        from JDebug.log import *


jdb_lastresult = ""
jdb_cursor = ""
prev_lines = ""
current_line = ""
jdb_cursor_position = 0
jdb_last_cursor_view = None
jdb_bkp_layout = {}
jdb_bkp_window = None
jdb_bkp_view = None
jdb_shutting_down = False
jdb_process = None
jdb_run_status = None
icon = None


class JDBView(object):
    """
    Base class for each view (tab) in the debugger
    """
    def __init__(self, name, s=True, settingsprefix=None):
        self.queue = Queue.Queue()
        self.name = name
        self.closed = True
        self.doScroll = s
        self.view = None
        self.settingsprefix = settingsprefix
        self.timer = None
        self.lines = ""
        self.lock = threading.RLock()

    def is_open(self):
        return not self.closed

    def open_at_start(self):
        if self.settingsprefix is not None:
            return get_setting("%s_open" % self.settingsprefix, False)
        return False

    def open(self):
        if self.view is None or self.view.window() is None:
            if self.settingsprefix is not None:
                sublime.active_window().focus_group(get_setting("%s_group" % self.settingsprefix, 0))
            self.create_view()

    def close(self):
        if self.view is not None:
            if self.settingsprefix is not None:
                sublime.active_window().focus_group(get_setting("%s_group" % self.settingsprefix, 0))
            self.destroy_view()

    def should_update(self):
        return self.is_open() and is_running() and jdb_run_status == "stopped"

    def set_syntax(self, syntax):
        if self.is_open():
            self.get_view().set_syntax_file(syntax)


    def timed_add(self):
        try:
            self.lock.acquire()
            lines = self.lines
            self.lines = ""
            self.timer = None
            self.queue.put((self.do_add_line, lines))
            sublime.set_timeout(self.update, 0)
        finally:
            self.lock.release()


    def add_line(self, line, now=True):
        if self.is_open():
            try:
                self.lock.acquire()
                self.lines += line
                if self.timer:
                    self.timer.cancel()
                if self.lines.count("\n") > 10 or now:
                    self.timed_add()
                else:
                    self.timer = threading.Timer(0.1, self.timed_add)
                    self.timer.start()
            finally:
                self.lock.release()

    def scroll(self, line):
        if self.is_open():
            self.queue.put((self.do_scroll, line))
            sublime.set_timeout(self.update, 0)

    def set_viewport_position(self, pos):
        if self.is_open():
            self.queue.put((self.do_set_viewport_position, pos))
            sublime.set_timeout(self.update, 0)

    def clear(self, now=False):
        if self.is_open():
            if not now:
                self.queue.put((self.do_clear, None))
                sublime.set_timeout(self.update, 0)
            else:
                self.do_clear(None)

    def create_view(self):
        self.view = sublime.active_window().new_file()
        self.view.set_name(self.name)
        self.view.set_scratch(True)
        self.view.set_read_only(True)
        ## Setting command_mode to false so that vintage
        ## does not eat the "enter" keybinding
        self.view.settings().set('command_mode', False)
        self.closed = False

    def destroy_view(self):
        sublime.active_window().focus_view(self.view)
        sublime.active_window().run_command("close")
        self.view = None
        self.closed = True

    def is_closed(self):
        return self.closed

    def was_closed(self):
        self.closed = True

    def fold_all(self):
        if self.is_open():
            self.queue.put((self.do_fold_all, None))

    def get_view(self):
        return self.view

    def do_add_line(self, line):
        self.view.run_command("jdb_view_add_line", {"line": line, "doScroll": self.doScroll})

    def do_fold_all(self, data):
        self.view.run_command("fold_all")

    def do_clear(self, data):
        self.view.run_command("jdb_view_clear")

    def do_scroll(self, data):
        self.view.run_command("goto_line", {"line": data + 1})

    def do_set_viewport_position(self, data):
        ## Shouldn't have to call viewport_extent, but it
        ## seems to flush whatever value is stale so that
        ## the following set_viewport_position works.
        ## Keeping it around as a WAR until it's fixed
        ## in Sublime Text 2.
        self.view.viewport_extent()
        self.view.set_viewport_position(data, False)

    def update(self):
        if not self.is_open():
            return
        try:
            while not self.queue.empty():
                cmd, data = self.queue.get()
                try:
                    cmd(data)
                finally:
                    self.queue.task_done()
        except:
            traceback.print_exc()

    def on_session_ended(self):
        if get_setting("%s_clear_on_end" % self.settingsprefix, True):
            self.clear()


class JdbViewClear(sublime_plugin.TextCommand):
    """
    Exposed command to clear the view
    """
    def run(self, edit):
        self.view.set_read_only(False)
        self.view.erase(edit, sublime.Region(0, self.view.size()))
        self.view.set_read_only(True)


class JdbViewAddLine(sublime_plugin.TextCommand):
    """
    Exposed command to add a line to the view
    """
    def run(self, edit, line, doScroll):
        self.view.set_read_only(False)
        self.view.insert(edit, self.view.size(), line)
        self.view.set_read_only(True)
        if doScroll:
            self.view.show(self.view.size())


class JDBVariable:
    """
    Class representing a variable returned by JDB
    """
    def __init__(self, vp):
        self.name = vp[0]
        self.value = vp[1]
        # self.parent = parent
        self.children = []
        self.line = 0
        self.is_expanded = False
        self.expression = None
        self.can_expand = False
        self.is_array = False

    def has_children(self):
        return self.can_expand

    def __str__(self):
        return "%s => %s" % (self.name, self.value)

    def format(self, indent="", output="", line=0):
        picon = " "
        # if self.has_children():
        #     if self.is_expanded:
        #         icon = "-"
        #     else:
        #         icon = "+"

        output += "%s%s%s\n" % (indent, picon, self)
        self.line = line
        line = line + 1
        indent += "    "
        if self.is_expanded:
            for child in self.children:
                output, line = child.format(indent, output, line)
        return (output, line)


class JDBVariablesView(JDBView):
    """
    Debugger view displaying local variables while at a breakpoint / stepping through
    """
    def __init__(self):
        super(JDBVariablesView, self).__init__("JDebug Variables", False, settingsprefix="variables")
        self.variables = []

    def open(self):
        super(JDBVariablesView, self).open()
        self.set_syntax("Packages/Java/Java.tmLanguage")
        if self.is_open() and jdb_run_status == "stopped":
            self.update_variables(False)

    def update_view(self):
        self.clear()

        output = ""
        line = 0
        expanded_regions = []
        collapsed_regions = []
        for local in self.variables:
            output, line = local.format(line=line)
            self.add_line(output)
        self.update()

        line = 0
        line = self.find_regions(self.variables, expanded_regions, collapsed_regions, line)

        pos_scope = get_setting("position_scope", "entity.name.class")
        collapsed_icon = icon_path("collapsed")
        expanded_icon = icon_path("expanded")
        jdb_variables_view.view.add_regions("jdebug.collapsed.position", expanded_regions, pos_scope, expanded_icon, sublime.HIDDEN)
        jdb_variables_view.view.add_regions("jdebug.expanded.position", collapsed_regions, pos_scope, collapsed_icon, sublime.HIDDEN)

        jdb_variables_view.update()


    def find_regions(self, variables, expanded_regions=[], collapsed_regions=[], line=0):
        for var in variables:
            line = line +1

            if var.has_children():
                if var.is_expanded:
                    expanded_regions.append(jdb_variables_view.view.full_line(jdb_variables_view.view.text_point(line-1, 0)))
                    line = self.find_regions(var.children, expanded_regions, collapsed_regions, line)
                else:
                    collapsed_regions.append(jdb_variables_view.view.full_line(jdb_variables_view.view.text_point(line-1, 0)))

        return line

    def add_variable(self, exp):
        v = self.create_variable(exp)
        if v:
            self.variables.append(v)
        return v

    def create_variable(self, exp):
        parts = exp.split(" = ")
        return JDBVariable(parts)

    def clear_view(self):
        self.variables = []
        self.clear()

    def update_variables(self):
        if not self.should_update():
            return
        self.clear_view()
        result = run_cmd("locals")
        if not "No local variables" in result:
            localLines = result.split("\n")
            for ll in localLines:
                if not "Method arguments:" in ll and not "Local variables:" in ll:
                    parts = ll.split(" = ")
                    var_vals = run_cmd("print %s" % parts[0])
                    if len(var_vals) != 0:
                        self.add_variable(var_vals)
            self.update_view()

    def get_variable_at_line(self, line, var_list=None):
        if var_list is None:
            var_list = self.variables
        if len(var_list) == 0:
            return None

        for i in range(len(var_list)):
            if var_list[i].line == line:
                return var_list[i]
            elif var_list[i].line > line:
                return self.get_variable_at_line(line, var_list[i - 1].children)
        return self.get_variable_at_line(line, var_list[len(var_list) - 1].children)


class JDBBreakpoint(object):
    """
    Class representing a breakpoint in JDebug
    """
    def __init__(self, filename="", line=0):
        self.original_filename = normalize(filename)
        self.original_line = line
        # self.clear()
        self.add()

    @property
    def line(self):
        return self.original_line

    @property
    def filename(self):
        return normalize(self.original_filename)

    def add(self):
        if is_running():
            break_cmd = "stop at"
            class_name = determine_class_from_file(self.original_filename)
            cmd = "%s %s:%d" % (break_cmd, class_name, self.original_line)
            out = run_cmd(cmd)
            if "is not a valid class name" in out or "Deferring breakpoint" in out:
                sublime.error_message("%s: %s" % ("Cannot locate class", class_name))
                return

    def remove(self):
        if is_running():
            break_cmd = "clear"
            class_name = determine_class_from_file(self.original_filename)
            cmd = "%s %s:%d" % (break_cmd, class_name, self.original_line)
            out = run_cmd(cmd)
            if "Not found:" in out:
                sublime.error_message("%s: %s:%d" % ("Cannot locate breakpoint", class_name, self.original_line))
                return

    def format(self):
        return "%s:%d\n" % (self.filename, self.line)


class JDBBreakpointView(JDBView):
    """
    Debugger view displaying all current breakpoints set in JDebug
    """
    def __init__(self):
        super(JDBBreakpointView, self).__init__("JDebug Breakpoints", s=False, settingsprefix="breakpoints")
        self.breakpoints = []

    def open(self):
        super(JDBBreakpointView, self).open()
        ## self.set_syntax("Packages/JDebug/jdb_disasm.tmLanguage")
        self.get_view().settings().set("word_wrap", False)
        if self.is_open():
            self.update_view()

    def on_session_ended(self):
        ## Intentionally not calling super
        # for bkpt in self.breakpoints:
        #     bkpt.clear()
        pass

    def update_marker(self, view):
        bps = []
        fn = view.file_name()
        if fn is None:
            return
        fn = normalize(fn)

        for bkpt in self.breakpoints:
            if bkpt.filename == fn and not (bkpt.line == jdb_cursor_position and fn == jdb_cursor):
                bps.append(view.full_line(view.text_point(bkpt.line - 1, 0)))

        view.add_regions("jdebug.breakpoints", bps,
                            get_setting("breakpoint_scope", "keyword.jdb"),
                            get_setting("breakpoint_icon", "circle"),
                            sublime.HIDDEN)

    def find_breakpoint(self, filename, line):
        filename = normalize(filename)
        for bkpt in self.breakpoints:
            if bkpt.filename == filename and bkpt.line == line:
                return bkpt
        return None


    def toggle_breakpoint(self, filename, line):
        bkpt = self.find_breakpoint(filename, line)
        if bkpt:
            bkpt.remove()
            self.breakpoints.remove(bkpt)
        else:
            self.breakpoints.append(JDBBreakpoint(filename, line))
        self.update_view()

    def sync_breakpoints(self):
        global breakpoints
        for bkpt in self.breakpoints:
            bkpt.add()
        update_view_markers()
        self.update_view()

    def update_view(self):
        if not self.is_open():
            return
        pos = self.get_view().viewport_position()
        self.clear()
        self.breakpoints.sort(key=lambda b: (b.filename, b.line))
        for bkpt in self.breakpoints:
            self.add_line(bkpt.format())
        self.set_viewport_position(pos)
        self.update()


jdb_console_view = JDBView("JDebug Console", settingsprefix="console")
jdb_variables_view = JDBVariablesView()
jdb_breakpoint_view = JDBBreakpointView()
jdb_views = [jdb_console_view, jdb_variables_view, jdb_breakpoint_view]

def update_view_markers(view=None):
    """
    Refresh the cursor position, breakpoint marker icons, etc
    """
    if view is None:
        view = sublime.active_window().active_view()

    fn = view.file_name()
    if fn is not None:
        fn = normalize(fn)
    pos_scope = get_setting("position_scope", "entity.name.class")
    pos_icon = get_setting("position_icon", "bookmark")

    cursor = []
    if fn == jdb_cursor and jdb_cursor_position != 0:
        cursor.append(view.full_line(view.text_point(jdb_cursor_position - 1, 0)))
    global jdb_last_cursor_view
    if jdb_last_cursor_view is not None:
        jdb_last_cursor_view.erase_regions("jdebug.position")
    jdb_last_cursor_view = view
    view.add_regions("jdebug.position", cursor, pos_scope, pos_icon, sublime.HIDDEN)

    if jdb_cursor_position != 0:
        view.sel().add(view.line(view.text_point(jdb_cursor_position - 1, 0)))

    jdb_breakpoint_view.update_marker(view)


count = 0


def run_cmd(cmd, block=True):
    """
    Send a command to JDB.  By default, will wait and return the response.  block=false to not wait for a response
    """
    global count
    global jdb_lastresult
    global prev_lines
    global current_line
    if not is_running():
        raise ValueError("Cannot run '%s'! JDB is not running" % cmd)

    prev_lines = ""
    current_line = ""

    timeout = 50
    timeoutcount = timeout/.001
    
    log_debug("jdb_%s: %s" % ("stdin", cmd))
    cmd = "%s\n" % cmd
    if jdb_console_view is not None:
        jdb_console_view.add_line("-> %s" % cmd, False)
    
    jdb_process.stdin.write(cmd.encode(sys.getdefaultencoding()))
    jdb_process.stdin.flush()
    
    if block:
        count = count + 1
        countstr = "%d^" % count
        i = 0
        while not jdb_lastresult.startswith(countstr) and i < timeout:
            i += 1
            time.sleep(0.1)
        if i >= timeout:
            raise ValueError("Command \"%s\" took longer than %d seconds to perform?" % (cmd, timeout))
        cmd_result = jdb_lastresult[len(countstr):]
        jdb_lastresult = ""
        return cmd_result


def wait_until_loaded():
    """
    Sleep the main thread until JDB is ready to go
    """
    i = 0
    log_debug("waiting until JDB is loaded...")
    while not jdb_loaded and i < 50:
        i = i + 1
        time.sleep(0.1)
        if i >= 50:
            return False
    log_debug("JDB is now loaded!")
    return True


def update_cursor():
    """
    Update cursor/marker/views upon hitting a breakpoint or stepping
    """
    global jdb_cursor
    global jdb_cursor_position

    if jdb_run_status != "running":
        res = run_cmd("where")

        first_line = res.split("\n")[0]
        c_start = first_line.find("] ") + 2
        del_idx = first_line.find(" (")
        c_end = first_line.rfind(".", 0, del_idx)
        l_start = first_line.find(":") + 1
        l_end = first_line.find(")")
        class_name = first_line[c_start:c_end]
        file_path = determine_file_from_class(class_name)

        if os.path.exists(file_path):
            jdb_cursor = file_path
            unformatedLineNo = re.sub(",", "", first_line[l_start:l_end])
            jdb_cursor_position = int(unformatedLineNo)

            sublime.active_window().focus_group(get_setting("file_group", 0))
            sublime.active_window().open_file("%s:%d" % (jdb_cursor, jdb_cursor_position), sublime.ENCODED_POSITION)
            update_view_markers()
            jdb_variables_view.update_variables()
        else:
            sublime.error_message("Unable to find class: %s" % class_name)
            #TODO - need to figure out how to handle this situation better
            sublime.active_window().run_command("jdb_continue")


def jdboutput(pipe):
    """
    Handle output from JDB process
    """
    global count
    global jdb_process
    global jdb_loaded
    global jdb_lastresult
    global jdb_run_status
    global current_line
    global prev_lines
    jdb_loaded = False
    prev_lines = ""
    current_line = ""
    thread_out_regex = re.compile("^Thread-\d+\[\d+\]$")
    

    while True:
        try:
            nextbyte = pipe.read(1)
            if not nextbyte:
                break
            nextchar = nextbyte.decode(sys.getdefaultencoding())

            countstr = "%d^" % count

            if nextchar == ">" and len(current_line) == 0:
                if jdb_loaded:
                    log_debug("jdb_%s: %s" % ("stdout" if pipe == jdb_process.stdout else "stderr", prev_lines))
                    jdb_console_view.add_line("<-%s\n" % prev_lines, False)
                    jdb_lastresult = "%s%s" % (countstr, prev_lines)
                    current_line = ""
                    prev_lines = ""
                    continue
                else:
                    current_line = ""
                    prev_lines = ""
                    jdb_loaded = True
                    continue
            if nextchar == ">" and len(current_line) > 0:
                current_line = ""
                prev_lines = ""
                continue
            if nextchar == "\n":
                if len(prev_lines) > 0:
                    prev_lines = "%s\n" % (prev_lines)
                if current_line != " ":
                    prev_lines = "%s%s" % (prev_lines, current_line)
                current_line = ""
            else:
                if nextchar != "\r":
                    current_line = current_line + nextchar

            if thread_out_regex.match(current_line) is not None:
                unsol_result = "%s%s" % (prev_lines, current_line)
                log_debug("jdb_%s: %s" % ("stdout" if pipe == jdb_process.stdout else "stderr", unsol_result))
                jdb_console_view.add_line("<-%s\n" % unsol_result, False)
                if jdb_run_status == "running":
                    jdb_run_status = "stopped"
                    sublime.set_timeout(update_cursor, 0)
                else:
                    jdb_lastresult = "%s%s" % (countstr, prev_lines)
                current_line = ""
                prev_lines = ""


            if re.match("^\[.*\].*\[\d+\]$", current_line) is not None:
                if re.match("^(Breakpoint hit|Step completed)", prev_lines) is not None:
                    log_debug("Breakpoint Hit ")
                    unsol_result = "%s%s" % (prev_lines, current_line)
                    log_debug("jdb_%s: %s" % ("stdout" if pipe == jdb_process.stdout else "stderr", unsol_result))
                    jdb_console_view.add_line("<-%s\n" % unsol_result, False)
                    if jdb_run_status == "running":
                        jdb_run_status = "stopped"
                        sublime.set_timeout(update_cursor, 0)
                    else:
                        jdb_lastresult = "%s%s" % (countstr, prev_lines)
                    current_line = ""
                    prev_lines = ""

        except:
            traceback.print_exc()
    if pipe == jdb_process.stdout:
        log_debug("JDB session ended")
        jdb_console_view.add_line("## JDB session ended ##\n")
        sublime.status_message("JDB session ended")
    global jdb_cursor_position
    jdb_cursor_position = 0
    jdb_run_status = None
    sublime.set_timeout(update_view_markers, 0)

    for view in jdb_views:
        sublime.set_timeout(view.on_session_ended, 0)
    sublime.set_timeout(cleanup, 0)


def cleanup():
    """
    Cleanup workspace after disconnecting from JDB
    """
    if get_setting("close_views", True):
        for view in jdb_views:
            view.close()
    if get_setting("push_pop_layout", True):
        jdb_bkp_window.set_layout(jdb_bkp_layout)
        jdb_bkp_window.focus_view(jdb_bkp_view)


def is_running():
    """
    Check JDB process state
    """
    return jdb_process is not None and jdb_process.poll() is None


def go_to_run_state():
    """
    Toggle current JDB state to "running" and clear variables
    """
    global jdb_run_status
    jdb_variables_view.clear_view()
    jdb_run_status = "running"


class JdbLaunch(sublime_plugin.WindowCommand):
    """
    Launch the JDB process and add any breakpoints that may have been set prior
    """
    def run(self):
        global jdb_process
        global jdb_run_status
        global jdb_bkp_window
        global jdb_bkp_view
        global jdb_bkp_layout
        global jdb_shutting_down
        global DEBUG
        global icon
        view = self.window.active_view()
        set_log_level(get_setting("debug", False, view))
        
        icon = icon_path(icon_name="collapsed")
        log_debug("%s" % icon)

        if jdb_process is None or jdb_process.poll() is not None:
            commandline = get_setting("commandline", view=view)
            path = get_setting("workingdir", "/tmp", view)

            if commandline == "notset" or path == "notset":
                sublime.error_message("You have not configured the plugin correctly, the default configuration file and your user configuration file will open in a new window")
                sublime.run_command("new_window")
                wnd = sublime.active_window()
                wnd.set_layout({
                    "cols": [0.0, 0.5, 1.0],
                    "rows": [0, 1.0],
                    "cells": [[0,0,1,1], [1,0,2,1]],
                })
                v = wnd.open_file("%s/User/JDebug.sublime-settings" % sublime.packages_path())
                v2 = wnd.open_file("%s/JDebug/JDebug.sublime-settings" % sublime.packages_path())
                wnd.set_view_index(v2, 1, 0)
                return
            if not os.path.exists(path):
                sublime.error_message("The directory given does not exist: %s" % path)
                return
            jdb_process = subprocess.Popen(commandline, shell=True, cwd=path,
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            jdb_bkp_window = sublime.active_window()
            ##back up current layout before opening the debug one
            ##it will be restored when debug is finished
            jdb_bkp_layout = jdb_bkp_window.get_layout()
            jdb_bkp_view = jdb_bkp_window.active_view()
            jdb_bkp_window.set_layout(
                get_setting("layout",
                    {
                        "cols": [0.0, 0.5, 1.0],
                        "rows": [0.0, 0.75, 1.0],
                        "cells": [[0, 0, 2, 1], [0, 1, 1, 2], [1, 1, 2, 2]]
                    }
                )
            )

            for view in jdb_views:
                if view.is_closed() and view.open_at_start():
                    view.open()
                view.clear()

            jdb_shutting_down = False

            t = threading.Thread(target=jdboutput, args=(jdb_process.stdout,))
            t.start()
            t = threading.Thread(target=jdboutput, args=(jdb_process.stderr,))
            t.start()

            jdb_console_view.add_line("## Attaching JDB... ##\n")
            sublime.status_message("Attaching JDB...")
            has_loaded = wait_until_loaded()
            if not has_loaded:
                sublime.error_message("JDB did not start.  Check that the Java process is running and listening and that your settings are correct")
                run_cmd("quit", False)
                return
            go_to_run_state()
            jdb_console_view.add_line("## JDB Attached ##\n")
            sublime.status_message("JDB Attached")
            jdb_breakpoint_view.sync_breakpoints()
        else:
            sublime.status_message("JDB is already running!")

    def is_enabled(self):
        return not is_running()

    def is_visible(self):
        return not is_running()


class JdbContinue(sublime_plugin.WindowCommand):
    """
    Resume running the Java application if currently paused
    """
    def run(self):
        global jdb_cursor_position
        jdb_cursor_position = 0
        update_view_markers()
        go_to_run_state()
        run_cmd("cont", False)

    def is_enabled(self):
        return is_running() and jdb_run_status != "running"

    def is_visible(self):
        return is_running()


class JdbExit(sublime_plugin.WindowCommand):
    """
    End the JDB session, if active
    """
    def run(self):
        global jdb_shutting_down
        jdb_shutting_down = True
        # wait_until_stopped()
        run_cmd("quit", False)

    def is_enabled(self):
        return is_running()

    def is_visible(self):
        return is_running()


class JdbStepOver(sublime_plugin.WindowCommand):
    """
    Step over, if currently paused
    """
    def run(self):
        go_to_run_state()
        run_cmd("next", False)

    def is_enabled(self):
        return is_running() and jdb_run_status != "running"

    def is_visible(self):
        return is_running()


class JdbStepInto(sublime_plugin.WindowCommand):
    """
    Step into, if currently paused
    """
    def run(self):
        go_to_run_state()
        run_cmd("step", False)

    def is_enabled(self):
        return is_running() and jdb_run_status != "running"

    def is_visible(self):
        return is_running()


class JdbStepOut(sublime_plugin.WindowCommand):
    """
    Step out, if currently paused
    """
    def run(self):
        go_to_run_state()
        run_cmd("step up", False)

    def is_enabled(self):
        return is_running() and jdb_run_status != "running"

    def is_visible(self):
        return is_running()


class JdbIgnored(sublime_plugin.WindowCommand):
    """
    Empty command, to be sure the keyboard shortcuts don't perform some other action
    """
    def run(self):
        pass


class JdbToggleBreakpoint(sublime_plugin.TextCommand):
    """
    Set a breakpoint at the current cursor
    """
    def run(self, edit):
        fn = self.view.file_name()
        if fn is not None:
            for sel in self.view.sel():
                line, col = self.view.rowcol(sel.a)
                jdb_breakpoint_view.toggle_breakpoint(fn, line + 1)
        update_view_markers(self.view)


class JdbAddExpression(sublime_plugin.WindowCommand):
    def run(self):
        self.set_expression()

    def set_expression(self):
        # Show user input for setting watch expression
        self.window.show_input_panel('Watch expression', '', self.on_done, self.on_change, self.on_cancel)

    def is_enabled(self):
        return is_running() and (jdb_variables_view.is_open())

    def on_done(self, expression):
        # User did not set expression
        if not expression:
            return
        evaluate_expression(expression)

    def on_change(self, line):
        pass

    def on_cancel(self):
        pass


class JdbExpand(sublime_plugin.TextCommand):
    def run(self, edit):
        for sel in self.view.sel():
            line, col = self.view.rowcol(sel.a)
            var = jdb_variables_view.get_variable_at_line(line)

            if var.has_children():
                evaluate_expression(var.expression, var)

    def is_enabled(self):
        return is_running() and (jdb_variables_view.is_open()) and (self.view.id() == jdb_variables_view.get_view().id())


class JdbPrint(sublime_plugin.TextCommand):
    def run(self, edit):
        sel_variable = self.view.substr(self.view.sel()[0])
        self.on_done(sel_variable)

    def is_enabled(self):
        return is_running() and (jdb_variables_view.is_open())

    def on_done(self, text):
        evaluate_expression(text)


def evaluate_expression(expression, parent=None):
    var_vals = run_cmd("dump %s" % expression)

    # may be the variable is getting expanded is an array
    is_expanding_array = False
    if parent is not None:
        is_expanding_array = parent.is_array

    if is_expanding_array:
        localLines = var_vals.split("\n")[1].split(",")
    else:
        localLines = var_vals.split("\n")

    # determine if the variable is array
    if is_expanding_array == False:
        if (localLines[0].endswith("{") and (localLines[1].find(",") != -1 or localLines[1].find(":") == -1)):
            is_expanding_array = True
            localLines = localLines[1].split(",")
            v = jdb_variables_view.add_variable(" " + expression + " = ")
            v.expression = expression

    children = []
    array_indx = 0
    for ll in localLines:
        if ll.endswith("{"):
            # For complex objects create expression as parent
            if parent is None:
                v = jdb_variables_view.add_variable(" " + expression + " = ")
                v.expression = expression


        if (ll.find("{") == -1 and ll.find("}") == -1):
            if ll.find("Internal exception") != -1:
                break

            is_object = ll.find("instance of ")
            is_array = False
            if is_object != -1:
                #Find out if it is Array
                if re.match(".*\[\d+\]\s\(id=\d+\)$$", ll) is not None:
                    is_array = True

            newline = ll
            can_expand = False
            if (is_object != -1):
                newline = ll[0:is_object] + ll[is_object+12:]
                can_expand = True

            if is_expanding_array:
                newline = "    [%d] = %s" % (array_indx, newline)
            else:
                newline = newline.replace(":", " =")

            # if parent is passed then add the children
            if parent is not None:
                v = jdb_variables_view.create_variable(newline)
                children.append(v)
            else:
                v = jdb_variables_view.add_variable(newline)
            if v:
                if is_expanding_array:
                    v.expression = expression + "[" + str(array_indx) + "]"
                else:
                    v.expression = expression + "." + v.name.strip()
                v.can_expand = can_expand
                v.is_array = is_array

            array_indx += 1

    if parent is not None:
        parent.children = children
        parent.is_expanded = True
    jdb_variables_view.update_view()


class JdbEventListener(sublime_plugin.EventListener):
    """
    Respond to system-level view events
    """
    def on_query_context(self, view, key, operator, operand, match_all):
        if key == "jdb_running":
            return is_running() == operand
        elif key.startswith("jdb_"):
            v = jdb_variables_view
            if key.endswith("open"):
                return v.is_open() == operand
            else:
                if v.get_view() is None:
                    return False == operand
                return (view.id() == v.get_view().id()) == operand
        return None

    def on_activated(self, view):
        if view.file_name() is not None:
            update_view_markers(view)

    def on_load(self, view):
        if view.file_name() is not None:
            update_view_markers(view)

    def on_close(self, view):
        for v in jdb_views:
            if v.is_open() and view.id() == v.get_view().id():
                v.was_closed()
                break


class JdbOpenConsoleView(sublime_plugin.WindowCommand):
    """
    Open the Console debugger view
    """
    def run(self):
        jdb_console_view.open()

    def is_enabled(self):
        return not jdb_console_view.is_open()

    def is_visible(self):
        return not jdb_console_view.is_open()


class JdbOpenVariablesView(sublime_plugin.WindowCommand):
    """
    Open the Variables debugger view
    """
    def run(self):
        jdb_variables_view.open()

    def is_enabled(self):
        return not jdb_variables_view.is_open()

    def is_visible(self):
        return not jdb_variables_view.is_open()


class JdbOpenBreakpointView(sublime_plugin.WindowCommand):
    """
    Open the Breakpoints debugger view
    """
    def run(self):
        jdb_breakpoint_view.open()

    def is_enabled(self):
        return not jdb_breakpoint_view.is_open()

    def is_visible(self):
        return not jdb_breakpoint_view.is_open()
