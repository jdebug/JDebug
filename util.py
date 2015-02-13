import sublime

import os
import sys

try:
    from .settings import *
except:
    try:
        from settings import *
    except:
        from JDebug.settings import *

def determine_class_from_file(filename):
    """
    Figure out the Java package/class from absolute file name
    """
    class_name = filename.replace("\\", "/")
    src_prefix = get_setting("source_path_prefix", "/src/main/java/")
    class_name = class_name[class_name.find(src_prefix) + len(src_prefix):]
    class_name = class_name.replace("/", ".").replace(".java","")
    return class_name

def determine_file_from_class(class_name):
    """
    Figure out the absolute file name from a Java package/class
    """
    if int(sublime.version()) < 3000:
        project_root = get_setting("workingdir", "/tmp")
    else:
        project_root = sublime.active_window().project_data()['folders'][0]['path']
    src_prefix = project_root + get_setting("source_path_prefix", "/src/main/java/")
    src_prefix = src_prefix.replace("\\", "/")
    filename = class_name.replace(".", "/")
    filename = src_prefix + filename + ".java"
    return filename

def icon_path(icon_name):
    if int(sublime.version()) < 3000:
        path = '../JDebug'
        extn = ''
    else:
        path = os.path.realpath(__file__)
        root = os.path.split(os.path.dirname(path))[1]

        path = 'Packages/' + os.path.splitext(root)[0]
        extn = '.png'

    return "/".join([path, 'icons', icon_name + extn])


def normalize(filename):
    """
    Normalize a file path
    """
    if filename is None:
        return None
    ##return os.path.abspath(os.path.normcase(filename))
    # In windows the path seperator is '\' and make it uniform for all OS
    return os.path.abspath(filename).replace("\\", "/")
