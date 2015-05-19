#!/usr/bin/env python

from setuptools import setup

setup(name='chiselc',
      version='0.1',
      description='Chisel Build Script',
      author='Richard Lin',
      author_email='rlin@eecs.berkeley.edu',
      url='https://chisel.eecs.berkeley.edu',
      #scripts=['chiselc.py'],
      packages=['chiselc'],
      entry_points={
          'console_scripts':['chiselc = chiselc:main']
      },
)
