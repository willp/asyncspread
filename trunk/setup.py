#!/usr/bin/env python
from distutils.core import setup
import asyncspread

setup (name = 'asyncspread',
     version = '0.1.0',
     description = 'Asynchronous Spread Client',
     long_description = asyncspread.asyncspread.__doc__,
     author = 'J. Will Pierce',
     author_email = 'willp@nuclei.com',
     url = 'http://http://code.google.com/p/asyncspread/',
     packages = ['asyncspread'])
