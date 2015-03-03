# JDebug #

## Description ##
JDebug is the Java Debugging Sublime Text plugin. It uses the Remote debugging features of JDB command.

## More Details

Get More Information from the tutorial - <http://blog.jdebugger.com/2015/02/jdebug-java-debugging-plugin-for.html>  

## Usage ##
**This is a beta version tested in Weblogic 11g(Windows, Ubuntu 14.04 and OS X Mavericks 10.9) with Sublime Text 2 & 3 and Java 1.6.0_29**


Edit the *SublimeJDB.sublime-settings*.  In particular,

- **workingdir** - This should be set for Sublime Text 2. Set the project root like c:/workspace/TestService
- **commandline** - Set to the command line string that will be used to launch JDB
- **source_path_prefix** - Set to the folder where the java package resides,  usually /"src/" but for maven project it is "/src/main/java/"

To debug:

![screenshot](https://raw.githubusercontent.com/jdebug/JDebug/master/jdebugging.gif)


## Support ##
**Please donate for supporting the devlopment or click the ad in the above tutorial page.**
