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
files. Each of the three elements are separated by a ':'. If a value is not
given for a particular element, that that element is not changed on the
encountered files.

directories_spec works just like files_spec, but it is applied to
directories. In addition, if you give a '-' as the owner or group, the same
owner and group will be taken from the files_spec.

If files_spec is '::' then no operations are done on files.  Similarly, if
directories_spec is '::' then no operations are done on directories.

Examples:

  chogm www-data:www-data:644 -:-:755 /pub/www/*

    Change all files in /pub/www to have an owner and group of www-data, and
    permissions of -rw-r--r--. Also change all directories in /pub/www/ to
    have an owner and group of www-data, but permissions of -rwxr-xr-x.  This
    is equivilent to the following shell commands:
      $ chown www-data:www-group /pub/www/*
      $ find /pub/www -maxdepth 1 -type f | xargs chmod 644
      $ find /pub/www -maxdepth 1 -type d | tail -n +2 | xargs chmod 755 


  chogm -R :: ::u+x ~/tmp

    Add the execute bit for the owner of ~/tmp and any directories under it.
    This is the same as doing:
       $ find ~/tmp -type d | xargs chmod u+x

"""

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
	"hold an owner, group, and mode"
	def __init__(self):
		self.owner = None
		self.group = None
		self.mode = None

class Worker:
	'''a worker class that uses python multiprocessing module clone itself, launch an OS
	   processes, and then catch new work from a multiprocessing.Pipe and send it to the
	   OS process to get done.
	
	   The OS process is xargs, so that we don't have to execute a new OS process for
	   every file we want to modify.  We just send it to standard in, and let xargs take
	   care of how often it actually need to execute the chmod, chgrp or chmod
	'''
	def __init__(self, cmd, arg, verbose=False, debug=False):
		self.cmd = cmd
		self.arg = arg
		self.verbose = verbose
		self.debug = debug
		# set up a pipe so we can communicate with our multiprocessing.Process.
		# The parent side of the pipe is the writer, we write filenames into it.
		# The child side of the pipe is the reader.  The child reads files out of
		# the pipe and puts them on stdin of the unix xargs subproces
		self.pipe_reader, self.pipe_writer = mp.Pipe(duplex = False)
		self.p = mp.Process(target=self.runner,args=(cmd,arg,))
		self.p.start()
		###self.pipe_reader.close()  # this is the parent so we close the reading end of the pipe

	def name(self):
		'''return the name of this worker: the command it runs and the first argument for that command
		
		   Examples: 'chown www-data' or 'chmod 755'
		
		'''
		return "%s %s" % (self.cmd, self.arg)

	def add(self, file):
		'''send a filename to the writing end of the pipe'''
		# this is called by the parent, and writes stuff into the pipe for the child to read out
		self.pipe_writer.send(file)
		
	def runner(self, cmd, arg):
		###self.pipe_writer.close()  # this is the child so we close the writing end of the pipe
		xargs = subprocess.Popen(["xargs","echo", cmd, arg], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		if self.debug:
			print >>sys.stderr, "--worker '%s' started xargs subprocess pid=%i" % (self.name(), xargs.pid)
		while True:
			try:
				# receive work from our pipe
				file = self.pipe_reader.recv()
				# if we get message that there is None work, then we are done
				if file is None:
					if self.debug:
						print >>sys.stderr, "--worker '%s' received poisen pill" % self.name()
					break
				# send the file to the stdin of the xargs process
				print >>xargs.stdin, file
				if self.debug:
					print >>sys.stderr, "--worker '%s' received %s" % (self.name(), file)
			except EOFError:
				break

		# we have broken out of the loop, so that means we have no more work to do
		# gracefully close down the xargs process and catch the output
		(stdoutdata,stderrdata) = xargs.communicate()
		if self.debug:
			print >>sys.stderr, "--worker '%s' xargs pid=%i returncode=%i" % (self.name(), xargs.pid, xargs.returncode)
			print >>sys.stderr, "--worker '%s' xargs output=%s" % (self.name(), stdoutdata)
		#if self.verbose:
		#	print >>sys.stderr, stdoutdata
		#	print >>sys.stderr, stderrdata

	def gohome(self):
		if self.debug:
			print >>sys.stderr, "--worker '%s' joining mp.Process" % self.name()
		self.p.join()

class Manager:
	def __init__(self, fogm, dogm, verbose=False, debug=False):
		self.fogm = fogm
		self.dogm = dogm
		self.fchown = None
		self.dchown = None
		self.fchgrp = None
		self.dchgrp = None
		self.fchmod = None
		self.dchmod = None
		if fogm.owner:
			self.fchown = Worker('chown', fogm.owner, verbose, debug)
		if dogm.owner:
			self.dchown = Worker('chown', dogm.owner, verbose, debug)
		if fogm.group:
			self.fchgrp = Worker('chgrp', fogm.group, verbose, debug)
		if dogm.group:
			self.dchgrp = Worker('chgrp', dogm.group, verbose, debug)
		if fogm.mode:
			self.fchmod = Worker('chmod', fogm.mode, verbose, debug)
		if dogm.mode:
			self.fchmod = Worker('chmod', dogm.mode, verbose, debug)
		
	def do_file(self, file):
		"pass file to our subprocesses to change its owner, group and mode"
		if self.fchown:
			self.fchown.add(file)
		if self.fchgrp:
			self.fchgrp.add(file)
		if self.fchmod:
			self.fchmod.add(file)
		
	def do_dir(self, file):
		"pass a directory to our subprocesses to change its owner group and mode"
		if self.dchown:
			self.dchown.add(file)
		if self.dchgrp:
			self.dchgrp.add(file)
		if self.dchmod:
			self.dchmod.add(file)

	def finish(self):
		"close all of our workers"
		self.fire(self.fchown)
		self.fire(self.dchown)
		self.fire(self.fchgrp)
		self.fire(self.dchgrp)
		self.fire(self.fchmod)
		self.fire(self.dchmod)

	def fire(self, worker):
		"tell a worker there is no more work for them and send them home"
		if worker:
			# send the poisen pill
			worker.add(None)
			# and send the worker home
			worker.gohome()


def main(argv=None):
	if argv is None:
		argv = sys.argv

	shortopts = "hRv"
	longopts = [ "help", "recursive", "verbose", "debug" ]
	
	# parse command line
	recursive = False
	debug = False
	verbose = False
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
		if len(spec) <> 3:
			raise Usage('Invalid file specification') 
		fileOgm = Ogm()
		fileOgm.owner = spec[0]
		fileOgm.group = spec[1]
		fileOgm.mode = spec[2]

		spec = args.pop(0).split(':')
		if len(spec) <> 3:
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
		m = Manager(fileOgm, dirOgm, verbose, debug)
		
		for file in args:
			walktree(m, file, recursive, verbose)

		m.finish()
		return 0

	except Usage, err:
		print >>sys.stderr, err.msg
		print >>sys.stderr, "for help use --help"
		return 2

def walktree(p, top, recursive=False, verbose=False):
	try:
		if os.path.isfile(top):
			p.do_file(top)
		elif os.path.isdir(top):
			if verbose:
				print >>sys.stderr, "Processing directory %s" % top
			p.do_dir(top)
			if recursive:
				for f in os.listdir(top):
					walktree(p, os.path.join(top,f), recursive)
		else:
			print >>sys.stderr, "cannot access '%s': No such file or directory" % top
	except OSError, ose:
		print >>sys.stderr, ose


if __name__ == "__main__":
	sys.exit(main())
