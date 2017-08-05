#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright (c) 2007-2017, Jared Crapo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

"""Change the owner, group, and mode of some files with a single command

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
directories.

EXAMPLES

  chogm www-data:www-data:644 -:-:755 /pub/www/*

    Change all files in /pub/www to have an owner and group of www-data,
    and permissions of -rw-r--r--. Also change all directories in
    /pub/www/ to have an owner and group of www-data, but permissions of
    -rwxr-xr-x. This is equivilent to the following shell commands:

      $ chown www-data:www-group /pub/www/*
      $ find /pub/www -maxdepth 1 -type f | xargs chmod 644
      $ find /pub/www -maxdepth 1 -type d | tail -n +2 | xargs chmod 755 


  chogm -R :accounting:g+rw,o= :-:g=rwx,o= /mnt/acct

    Change the group of all files in /mnt/acct to be accounting, and
    make sure people in that group can read, write, and create files
    anywhere in that directory tree. Also make sure that the hoi palloi
    can't peek at accounting's files. This is the same as doing:

		$ chgrp -R accounting /mnt/acct
		$ find /mnt/acct -type f -print | xargs chmod g+rw,o=
		$ find /mnt/acct -type d -print | xargs chmod g=rwx,o= 


  find ~/src -depth 2 -type d -print | grep -v '/.git$' | chogm -R :staff:660 :-:770 -

    Assuming your ~/src directory contains a bunch of directories, each
    with their own git project, change all those files to have a group
    of staff and permissions of -rw-rw---- and all the directories to
    also have a group of staff but permissions of -rwxrwx---. While
    doing all of that, don't change the permissions of any of the files
    inside of .git directories.


REQUIREMENTS

This script uses the operating system commands xargs, chmod, chgrp, and
chmod to do it's work. It also uses the python multiprocessing module from
the standard library which was added in python 2.6, so it won't work with
python versions earlier than that. It won't work in python 3.x.

EXIT STATUS

 0  everything OK
 1  some operations not successful (ie permission denied on a directory)
 2  incorrect usage

"""

import sys
import os
import argparse
import stat
import multiprocessing as mp
import subprocess

class Usage(Exception):
	def __init__(self, msg):
		self.msg = msg

class Ogm:
	"""store an owner, group, and mode"""
	def __init__(self):
		self.owner = None
		self.group = None
		self.mode = None

class Worker:
	"""Launch an operating system process and feed it data
	
	a worker class that uses python multiprocessing module clone itself, launch an OS
	processes, and then catch new work from a multiprocessing.Pipe and send it to the
	OS process to get done.
	
	The OS process is xargs, so that we don't have to execute a new OS process for
	every file we want to modify.  We just send it to standard in, and let xargs take
	care of how often it actually need to execute the chmod, chgrp or chmod
	
	"""
	def __init__(self, cmd, arg):
		self.cmd = cmd
		self.arg = arg
		# set up a pipe so we can communicate with our multiprocessing.Process.
		# From the parent process, we write filenames into the child pipe and read error
		# messages from it.  From the child process, we read filenames from the parent pipe
		# and write error messages into it.
		self.pipe_parent, self.pipe_child = mp.Pipe(duplex = True)
		self.p = mp.Process(target=self.runner,args=(cmd,arg,))
		self.p.start()
		###self.pipe_parent.close()  # this is the parent so we close the reading end of the pipe

	def name(self):
		"""return the name of this worker
		
		the command it runs and the first argument for that command, ie 'chown www-data'
		
		"""
		return "%s %s" % (self.cmd, self.arg)

	def add(self, file):
		"""send a filename to the child process via a pipe"""
		# this is called by the parent, and writes a filename to the child pipe
		self.pipe_child.send(file)
		
	def runner(self, cmd, arg):
		"""Start a subprocess and feed it data from a pipe
		
		This function is run in a child process.  So we read from the parent
		pipe to get work to do, and write to the parent pipe to send error messages
		
		We also fire up an xargs subprocess to actually do the work, and feed stuff
		from our parent pipe to stdin of the subprocess.
		"""
		xargs = subprocess.Popen(["xargs",cmd, arg], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		if debug:
			print("--worker '%s' started xargs subprocess pid=%i" % (self.name(), xargs.pid), file=sys.stderr)
		while True:
			try:
				# receive work from our parent pipe
				filename = self.pipe_parent.recv()
				# if we get message that there is None work, then we are done
				if filename == None:
					if debug:
						print("--worker '%s' has no more work to do" % self.name(), file=sys.stderr)
					break
				# send the file to the stdin of the xargs process
				print(filename,file=xargs.stdin)
				if debug:
					print("--worker '%s' received %s" % (self.name(), filename), file=sys.stderr)
			except EOFError:
				break

		# we have broken out of the loop, so that means we have no more work to do
		# gracefully close down the xargs process, save the contents of stderr, and
		# write the exit code and the errors into the pipe to our parent
		(stdoutdata,stderrdata) = xargs.communicate()
		if debug:
			print("--worker '%s' xargs pid=%i returncode=%i" % (self.name(), xargs.pid, xargs.returncode), file=sys.stderr)
			print("--worker '%s' xargs stderr=%s" % (self.name(), stderrdata), file=sys.stderr)
		self.pipe_parent.send( (xargs.returncode, stderrdata.rstrip('\r\n')) )

	def gohome(self):
		if debug:
			print("--worker '%s' joining mp.Process" % self.name(), file=sys.stderr)
		(rtncode,errmsgs) = self.pipe_child.recv()
		self.p.join()
		return (rtncode,errmsgs)

class Manager:
	"""Start and manage all of the subprocesses"""
	def __init__(self, fogm, dogm, verbose=False):
		self.haveError = False
		self.fogm = fogm
		self.dogm = dogm
		self.verbose = verbose
		
		self.fchown = None
		self.dchown = None
		self.fchgrp = None
		self.dchgrp = None
		self.fchmod = None
		self.dchmod = None
		
		if fogm.owner:
			self.fchown = Worker('chown', fogm.owner)
		if dogm.owner:
			self.dchown = Worker('chown', dogm.owner)
		if fogm.group:
			self.fchgrp = Worker('chgrp', fogm.group)
		if dogm.group:
			self.dchgrp = Worker('chgrp', dogm.group)
		if fogm.mode:
			self.fchmod = Worker('chmod', fogm.mode)
		if dogm.mode:
			self.dchmod = Worker('chmod', dogm.mode)
		
	def do_file(self, file):
		"""pass file to our subprocesses to change its owner, group and mode"""
		if self.fchown:
			self.fchown.add(file)
		if self.fchgrp:
			self.fchgrp.add(file)
		if self.fchmod:
			self.fchmod.add(file)
		
	def do_dir(self, file):
		"""pass a directory to our subprocesses to change its owner group and mode"""
		if self.dchown:
			self.dchown.add(file)
		if self.dchgrp:
			self.dchgrp.add(file)
		if self.dchmod:
			self.dchmod.add(file)

	def report_information(self,message):
		"""report information to stderr if verbose is set"""
		if self.verbose:
			print(message, file=sys.stderr)

	def report_error(self, message):
		"""report an error by printing it to stderr"""
		self.haveError = True
		print(message, file=sys.stderr)

	def finish(self):
		"""fire all of our workers and return a proper shell return code"""
		self.fire(self.fchown)
		self.fire(self.dchown)
		self.fire(self.fchgrp)
		self.fire(self.dchgrp)
		self.fire(self.fchmod)
		self.fire(self.dchmod)
		if self.haveError:
			return 1
		else:
			return 0

	def fire(self, worker):
		"""tell a worker there is no more work for them and send them home"""
		if worker:
			# put the "no more work" paper in the inbox
			worker.add(None)
			# and send the worker home
			(rtncode,stderrdata) = worker.gohome()
			if rtncode != 0:
				self.report_error(stderrdata)			

def main(argv=None):

	parser = argparse.ArgumentParser(description='Change the owner, group, and mode of some files with a single command')
	parser.add_argument('-R', '--recursive', action='store_true', help='recurse through the directory tree of each filespec')
	parser.add_argument('-v', '--verbose', action='store_true', help='show progress')
	parser.add_argument('file_spec', nargs=1, help='owner:group:perms to set on files')
	parser.add_argument('directory_spec', nargs=1, help='owner:group:perms to set on directories')
	parser.add_argument('file', nargs='+', help='one or more files to operate on.  Use \'-\' to process stdin as a list of files')
	args = parser.parse_args()
	print(args)

	verbose = args.verbose
	recursive = args.recursive
	global debug
	debug = True

	spec = args.file_spec[0].split(':')
	if len(spec) != 3:
		parser.error('Invalid file_spec') 		
	fileOgm = Ogm()
	fileOgm.owner = spec[0]
	fileOgm.group = spec[1]
	fileOgm.mode = spec[2]

	spec = args.directory_spec[0].split(':')
	if len(spec) != 3:
		parser.error('Invalid directory_spec') 
	dirOgm = Ogm()
	dirOgm.owner = spec[0]
	dirOgm.group = spec[1]
	dirOgm.mode = spec[2]

	# start up the child processes
	m = Manager(fileOgm, dirOgm, verbose)
	
	# examine each of the files
	for filename in args.file:
		if filename == '-':
			while True:
				onefile = sys.stdin.readline()
				if onefile == '': break
				examine(m, onefile.rstrip('\r\n'), parser, recursive)
		else:
			examine(m, filename, parser, recursive)

	# and finish up
	return m.finish()

def examine(m, thisfile, parser, recursive=False):
	"""Recursively process a single file or directory"""
	try:
		if os.path.isfile(thisfile):
			m.do_file(thisfile)
		elif os.path.isdir(thisfile):
			m.do_dir(thisfile)
			if recursive:
				m.report_information("Processing directory %s...." % thisfile)
				try:
					for eachfile in os.listdir(thisfile):
						examine(m, os.path.join(thisfile, eachfile), parser, recursive)
				except OSError as e:
					# do nicer formatting for common errors
					if e.errno == 13:
						m.report_error("%s: %s: Permission denied" % (parser.prog, e.filename))
					else:
						m.report_error("%s: %s" % (parser.prog, e))
		else:
			m.report_error("%s: cannot access '%s': No such file or directory" % (parser.prog, thisfile))
	except OSError as ose:
		m.report_error("%s: %s" % (parser.prog, e))		


if __name__ == "__main__":
	sys.exit(main())
