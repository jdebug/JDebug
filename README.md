# JDebug #

## Description ##
JDebug plugin is the Java Remote Debugging plugin for Sublime Text based on [SublimeGDB](https://github.com/quarnster/SublimeGDB)

## Usage ##
**This is a beta version tested in Weblogic 11g(Windows and Ubuntu 14.04) with Sublime Text 3 and Java 1.6.0_29**


Edit the *SublimeJDB.sublime-settings*.  In particular,

- **commandline** - Set to the command line string that will be used to launch JDB
- **source_path_prefix** - Set to the folder where the java package resides,  usually /"src/" but for maven project it is "/src/main/java/"

To debug:

![screenshot](https://raw.githubusercontent.com/jdebug/JDebug/master/jdebugging.gif)
