#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2007, Jared Crapo
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

"""Change the owner, group, and mode with a single command

chogm [OPTIONS] files_spec directories_spec file [file file ...]
   -R, --recursive      recurse through the directory tree of each file
   -v, --verbose        show progress
   files_spec           owner:group:perms to set on files
   directories_spec     owner:group:perms to set on directories

files_spec tells what owner, group, and permissions should be given to any
files. Each of the three elements are separated by a ':'. If a value is
not given for a particular element, that that element is not changed on
the encountered files.

directories_spec works just like files_spec, but it is applied to
directories. In addition, if you give a '-' as the owner or group, the
same owner and group will be taken from the files_spec.

If files_spec is '::' then no operations are done on files. Similarly, if
directories_spec is '::' then no operations are done on directories.

EXAMPLES

  chogm www-data:www-data:644 -:-:755 /pub/www/*

    Change all files in /pub/www to have an owner and group of www-data,
    and permissions of -rw-r--r--. Also change all directories in
    /pub/www/ to have an owner and group of www-data, but permissions of
    -rwxr-xr-x. This is equivilent to the following shell commands:

      $ chown www-data:www-group /pub/www/*
      $ find /pub/www -maxdepth 1 -type f | xargs chmod 644
      $ find /pub/www -maxdepth 1 -type d | tail -n +2 | xargs chmod 755 


  chogm -R :: ::u+x ~/tmp

    Add the execute bit for the owner of ~/tmp and any directories under
    it. This is the same as doing:

		$ find ~/tmp -type d | xargs chmod u+x

REQUIREMENTS

This script uses the operating system commands xargs, chmod, chgrp, and
chmod to do it's work. It also uses the python multiprocessing module from
the standard library which was added in python 2.6, so it won't work with
python versions earlier than that. It won't work in python 3.x.

EXIT CODE

Exit code is 0 if all operations were successful. Exit code is 1 if some
operations were not successfull (ie permission denied on a directory).
Exit code is 2 if usage was incorrect.

"""

# TODO
#   add --exclude command line option to exclude certain patterns of files
#   read files from stdin so you can pipe the output of find into this

import sys
import os
import getopt
import stat
import multiprocessing as mp
import subprocess

class Usage(Exception):
	def __init__(self, msg):
		self.msg = msg

class Ogm:
	"""hold an owner, group, and mode"""
	def __init__(self):
		self.owner = None
		self.group = None
		self.mode = None

class Worker:
	"""a worker class that uses python multiprocessing module clone itself, launch an OS
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
		"""return the name of this worker: the command it runs and the first argument for that command
		
		   Examples: 'chown www-data' or 'chmod 755'
		
		"""
		return "%s %s" % (self.cmd, self.arg)

	def add(self, file):
		"""send a filename to the child process via a pipe"""
		# this is called by the parent, and writes a filename to the child pipe
		self.pipe_child.send(file)
		
	def runner(self, cmd, arg):
		"""This function is run in a child process.  So we read from the parent
		pipe to get work to do, and write to the parent pipe to send error messages
		
		We also fire up an xargs subprocess to actually do the work, and feed stuff
		from our parent pipe to stdin of the subprocess.
		"""
		xargs = subprocess.Popen(["xargs",cmd, arg], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		if debug:
			print >>sys.stderr, "--worker '%s' started xargs subprocess pid=%i" % (self.name(), xargs.pid)
		while True:
			try:
				# receive work from our parent pipe
				file = self.pipe_parent.recv()
				# if we get message that there is None work, then we are done
				if file is None:
					if debug:
						print >>sys.stderr, "--worker '%s' has no more work to do" % self.name()
					break
				# send the file to the stdin of the xargs process
				print >>xargs.stdin, file
				if debug:
					print >>sys.stderr, "--worker '%s' received %s" % (self.name(), file)
			except EOFError:
				break

		# we have broken out of the loop, so that means we have no more work to do
		# gracefully close down the xargs process, save the contents of stderr, and
		# write the exit code and the errors into the pipe to our parent
		(stdoutdata,stderrdata) = xargs.communicate()
		if debug:
			print >>sys.stderr, "--worker '%s' xargs pid=%i returncode=%i" % (self.name(), xargs.pid, xargs.returncode)
			print >>sys.stderr, "--worker '%s' xargs stderr=%s" % (self.name(), stderrdata)
		self.pipe_parent.send( (xargs.returncode, stderrdata.rstrip('\r\n')) )

	def gohome(self):
		if debug:
			print >>sys.stderr, "--worker '%s' joining mp.Process" % self.name()
		(rtncode,errmsgs) = self.pipe_child.recv()
		self.p.join()
		return (rtncode,errmsgs)

class Manager:
	def __init__(self, fogm, dogm):
		self.haveError = False
		self.fogm = fogm
		self.dogm = dogm
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
		if verbose:
			print >>sys.stderr, message

	def report_error(self, message):
		"""report an error by printing it to stderr"""
		self.haveError = True
		print >>sys.stderr, message

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
	if argv is None:
		argv = sys.argv

	shortopts = "hRv"
	longopts = [ "help", "recursive", "verbose", "debug" ]
	
	# parse command line
	# yes the global variables are a bit messy, but it's cleaner than passing them into
	# all of our classes
	global debug
	global verbose
	global ranAs
	debug = False
	verbose = False
	ranAs = os.path.basename(argv[0])

	recursive = False

	try:
		try:
			opts, args = getopt.getopt(argv[1:], shortopts, longopts)
		except getopt.error, msg:
			raise Usage(msg)
	
		# process options
		for opt, parm in opts:
			if opt in ("-h", "--help"):
				print >>sys.stderr, __doc__
				return 0
			if opt in ("-R", "--recursive"):
				recursive = True
			if opt in ("-v", "--verbose"):
				verbose = True
			if opt in ("--debug"):
				debug = True
	
		# process arguments
		spec = args.pop(0).split(':')
		if len(spec) != 3:
			raise Usage('Invalid file specification')
		fileOgm = Ogm()
		fileOgm.owner = spec[0]
		fileOgm.group = spec[1]
		fileOgm.mode = spec[2]

		spec = args.pop(0).split(':')
		if len(spec) != 3:
			raise Usage('Invalid directory specification') 
		dirOgm = Ogm()
		dirOgm.owner = spec[0]
		dirOgm.group = spec[1]
		dirOgm.mode = spec[2]
		# check for '-' which means to clone the argument from the file_spec
		if dirOgm.owner == '-':
			dirOgm.owner = fileOgm.owner
		if dirOgm.group == '-':
			dirOgm.group = fileOgm.group
		if dirOgm.mode == '-':
			dirOgm.mode = fileOgm.mode

		# start up the child processes
		m = Manager(fileOgm, dirOgm)
		
		# examine each of the files
		for filename in args:
			examine(m, filename, recursive)

		# and finish up
		return m.finish()

	except Usage, err:
		print >>sys.stderr, "%s: %s" % (ranAs, err.msg)
		print >>sys.stderr, "for more information use --help"
		return 2

def examine(m, thisfile, recursive=False):
	try:
		if os.path.isfile(thisfile):
			m.do_file(thisfile)
		elif os.path.isdir(thisfile):
			m.do_dir(thisfile)
			if recursive:
				m.report_information("Processing directory %s...." % thisfile)
				try:
					for eachfile in os.listdir(thisfile):
						examine(m, os.path.join(thisfile, eachfile), recursive)
				except OSError, e:
					# do nicer formatting for common errors
					if e.errno == 13:
						m.report_error("%s: %s: Permission denied" % (ranAs, e.filename))
					else:
						m.report_error("%s: %s" % (ranAs, e))
		else:
			m.report_error("%s: cannot access '%s': No such file or directory" % (ranAs, thisfile))
	except OSError, ose:
		m.report_error("%s: %s" % (ranAs, e))		


if __name__ == "__main__":
	sys.exit(main())
