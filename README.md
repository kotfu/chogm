chogm
-----

Change the owner, group and mode of some files with a single command

Usage
-----

chogm [OPTIONS] files_spec directories_spec file [file file ...]  
   -R, --recursive      recurse through the directory tree of each file  
   -v, --verbose        show progress  
   -h, --help           display this usage message  
   files_spec           owner:group:perms to set on files  
   directories_spec     owner:group:perms to set on directories  
   file                 one or more files to operate on.  Use '-' to  
                        process stdin as a list of files  

files_spec tells what owner, group, and permissions should be given to any
files. Each of the three elements are separated by a ':'. If a value is
not given for a particular element, that that element is not changed on
the encountered files.

directories_spec works just like files_spec, but it is applied to
directories. In addition, if you give a '-' as the owner or group, the
same owner and group will be taken from the files_spec.

Examples
--------

### Simple

    chogm www-data:www-data:644 -:-:755 /pub/www/*

Change all files in /pub/www to have an owner and group of www-data, and
permissions of -rw-r--r--. Also change all directories in /pub/www/ to
have an owner and group of www-data, but permissions of -rwxr-xr-x. This
is equivilent to the following shell commands:

    $ chown www-data:www-group /pub/www/*
    $ find /pub/www -maxdepth 1 -type f | xargs chmod 644
    $ find /pub/www -maxdepth 1 -type d | tail -n +2 | xargs chmod 755 

### More Complex

    chogm -R :accounting:g+rw,o= :-:g=rwx,o= /mnt/acct

Change the group of all files in /mnt/acct to be accounting, and make
sure people in that group can read, write, and create files anywhere in
that directory tree. Also make sure that the hoi palloi can't peek at
accounting's files. This is the same as doing:

    $ chgrp -R accounting /mnt/acct
    $ find /mnt/acct -type f -print | xargs chmod g+rw,o=
    $ find /mnt/acct -type d -print | xargs chmod g=rwx,o= 

### Using stdin

    find ~/src -depth 2 -type d -print | grep -v '/.git$' | chogm -R :staff:660 :-:770 -

Assuming your ~/src directory contains a bunch of directories, each with
their own git project, change all those files to have a group of staff
and permissions of -rw-rw---- and all the directories to also have a
group of staff but permissions of -rwxrwx---. While doing all of that,
don't change the permissions of any of the files inside of .git
directories.


Requirements
------------

This script uses the operating system commands xargs, chmod, chgrp, and
chmod to do it's work. It also uses the python multiprocessing module
from the standard library which was added in python 2.6, so it won't
work with python versions earlier than that. It won't work in python
3.x.

Exit Status
-----------

 0  everything OK
 1  some operations not successful (ie permission denied on a directory)
 2  incorrect usage


License
-------

Check the LICENSE file.  It's the MIT License, which means you can do whatever you want, as long as you keep the copyright notice.