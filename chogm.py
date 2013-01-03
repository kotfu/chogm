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

"""Module Docstring

 quickly change the owner, group, and mode of a bunch of files

 chogm [ -R | --recursive ] files_spec directories_spec file [file file ...]
   -R, --recursive		recursivly change 
   files_spec					owner:group:perms
   directories_spec		owner:group:perms
   If files_spec is '::' then no operations will be done on files
   If directories_spec is '::' then no operations will be done on directories

long usage message

shamelessly borrowed from the BDFL
http://www.artima.com/weblogs/viewpost.jsp?thread=4829

"""
import sys
import os
import getopt
import stat
import subprocess

class Usage(Exception):
	def __init__(self,msg):
		self.msg = msg

class Ogm:
	pass

def main(argv=None):
	if argv is None:
		argv = sys.argv

	# examples:
	#    shortopts = "f:s:qh"
	#    longopts = [ "format=", "size=", "quiet", "help" ]
	shortopts = "hR"
	longopts = [ "help", "recursive" ]
	
	# parse command line options
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
	
		# process arguments
		spec = args.pop(0).split(':')
		if len(spec) <> 3:
			raise Usage('Invalid file specification') 
		fogm = Ogm()
		fogm.owner = spec[0]
		fogm.group = spec[1]
		fogm.mode = spec[2]

		spec = args.pop(0).split(':')
		if len(spec) <> 3:
			raise Usage('Invalid directory specification') 
		dogm = Ogm()
		dogm.owner = spec[0]
		dogm.group = spec[1]
		dogm.mode = spec[2]

		for file in args:
			walktree(file, fogm, dogm, recursive)

	except Usage, err:
		print >>sys.stderr, err.msg
		print >>sys.stderr, "for help use --help"
		return 2

def walktree(top, fogm, dogm, recursive=False):
	try:
		if os.path.isfile(top):
			modify(top, fogm)
		elif os.path.isdir(top):
			modify(top, dogm)
			if recursive:
				for f in os.listdir(top):
					walktree(os.path.join(top,f), fogm, dogm, recursive)
		else:
			print >>sys.stderr, "cannot access '%s': No such file or directory" % top
	except OSError, ose:
		print >>sys.stderr, ose

def modify(file, ogm):
	if ogm.owner:
		subprocess.call(('chown', ogm.owner, file))
	if ogm.group:
		subprocess.call(('chgrp', ogm.group, file))
	if ogm.mode:
		subprocess.call(('chmod', ogm.mode, file))

if __name__ == "__main__":
	sys.exit(main())