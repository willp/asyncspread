#!/usr/bin/env python
from distutils.core import setup
from asyncspread import *

setup (name = 'asyncspread',
     version = '0.1.1',
     description = 'Asynchronous Spread Client',
     long_description = asyncspread.AsyncSpread.__doc__,
     author = 'J. Will Pierce',
     author_email = 'willp@nuclei.com',
     license = 'GNU Lesser General Public License 3 or later',
     url = 'http://http://code.google.com/p/asyncspread/',
     packages = ['asyncspread'],
     keywords = 'spread client asynchronous pubsub channel messaging broker multicast ipc',
    classifiers = [
        "Development Status :: 3 - Alpha",
        "Environment :: No Input/Output (Daemon)",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 2.4",
        "Programming Language :: Python :: 2.5",
        "Programming Language :: Python :: 2.6",
        # TODO: Test with Python 2.7
        #"Programming Language :: Python :: 2.7",
        "Topic :: System :: Distributed Computing",
        "Topic :: Software Development :: Libraries :: Python Modules"
    ],

     )
