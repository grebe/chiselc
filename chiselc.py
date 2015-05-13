#!/usr/bin/env python

import argparse
import fnmatch
import logging
import os
import subprocess
import sys

class Package(object):
  """A package definition object
  """
  def __init__(self, package_definition_filepath):
    pass
  
  def get_pkgname(self):
    """Returns the package name, a globally unique identifier which consists of
    the name and the version number.
    """
    return self.get_name() + '-' + self.get_version()
  
  def get_name(self):
    return 'chisel'
  
  def get_version(self):
    return '1.0'
  
  def get_dependencies(self):
    """Returns dependencies as a list of Packages.
    """
    # TODO make this parse
    return []
  
  def get_field(self, fieldname, include_private=True):
    """Returns the value of an arbitrary field"""
    #TODO make this parse
    if fieldname == 'scalacopts':
      return ["-deprecation", 
              "-feature", 
              "-language:reflectiveCalls", 
              "-language:implicitConversions", 
              "-language:existentials"]
    elif fieldname == "classpath":
      return ["chisel.jar"]
    else:
      assert False
    
  def get_field_recursive(self, fieldname):
    # do a BFS over dependencies
    fringe = self.get_dependencies()
    field_contents = self.get_field(fieldname, True)
    seen = set()
    while fringe:
      dependency_package = fringe.pop(0)
      seen += dependency_package.get_pkgname()
      field_contents.extend(dependency_package.get_field(fieldname, False))
      dependencies = [dep for dep in dependency_package.get_dependencies()
                      if dep not in seen]
      fringe.push(dependencies)
    return field_contents

class PackageCollection(object):
  """Abstract base class for package collections, a listing of installed
  packages. 
  """
  def __init__(self, collection_dir):
    self.collection_dir = collection_dir
    
  def get_package(self, package_name):
    """Returns the argument package as a Package object, or None if it doesn't 
    exist.
    """
    # TODO make this parse
    if package_name == "chisel":
      return Package("bleh")
    else:
      assert False

class PortageInstalledPackage(Package):
  """Installed package for Portage.
  """
  def get_package(self, package_name):
    """Returns the argument package as a Package object, or None if it doesn't 
    exist.
    """
    pass
      
class PortagePkgList(PackageCollection):
  """Package collection for Portage, usually under /var/db/pkg.
  """
  def __init__(self, package_definition_filepath):
    pass
  
  def get_pkgname(self):
    pass
  
  def get_name(self):
    pass
  
  def get_version(self):
    pass
  
  def get_dependencies(self):
    pass
  
  def get_field(self, fieldname, include_private=True):
    pass
  

if __name__ == "__main__":
  logging.basicConfig(level=logging.DEBUG)
  logger = logging.getLogger(__name__)
  
  print(sys.argv)
  
  parser = argparse.ArgumentParser(description="Chisel compiler wrapper script")
  parser.add_argument('sourceDirs', nargs='+',
                      help="""list of source directories containing Chisel code,
                            scanned recursively""")
  parser.add_argument('buildDir', help="directory to place build output files")
  parser.add_argument('--pkgsDir', default=None,
                      help="""directory with package definition files and 
                              contents, used when resolving dependencies""")
  parser.add_argument('--pkgName', help="package name")
  parser.add_argument('--dependencies', nargs='*', help="list of dependencies")
  parser.add_argument('--scalacOpts', nargs='+', 
                      help="list of arguments to pass to scalac")
  parser.add_argument('--outputJar', default=None,
                      help="filename and path of output JAR")

  args = parser.parse_args()

  pkgs_dir = os.path.abspath(args.pkgsDir)

  package_collection = PackageCollection(pkgs_dir)
  packages = []
  # TODO remove hardcoded, use pkgname / dependencies
  # package = packages.get_package('chisel')
  # TODO allow specifying dependencies instead

  # Get all the source files
  source_files = []
  for source_dir in args.sourceDirs:
    for root, _, filenames in os.walk(source_dir):
      for filename in fnmatch.filter(filenames, '*.scala'):
        source_files.append(os.path.join(root, filename))
  logging.info("Found %i source files", len(source_files))
  
  scalac_args = ['scalac']
  scalac_args.extend(source_files)
  scalac_args.extend(['-d', os.path.abspath(args.buildDir)])

  scalacopts = []  
  for package in packages:
    scalacopts.extend(package.get_field_recursive('scalacopts'))
  scalacopts.extend(args.scalacOpts)
  scalacopts = ["-" + scalacopt for scalacopt in scalacopts]
  if scalacopts:
    logging.debug("Using scalacopts: %s", scalacopts)
    scalac_args.extend(scalacopts)
    
  # TODO: support Windows OS (uses semicolon for classpath separator)
  classpaths = ['/usr/share/java/junit4.jar', '/usr/share/java/scalatest_2.10-2.2.4.jar']
  #classpaths = []
  for package in packages:
    classpaths.extend(package.get_field_recursive('classpath'))
  if classpaths:    
    classpaths = [os.path.join(pkgs_dir, classpath) for classpath in classpaths]
    classpath_str = ':'.join(classpaths)
  
    logging.debug("Using classpath: %s", classpath_str)
    scalac_args.extend(['-classpath', classpath_str])
  
  logging.info("Running scalac")
  scalac_returncode = subprocess.call(scalac_args)
  logging.info("scalac done")
  
  if scalac_returncode != 0:
    logging.error("scalac returned nonzero return code: %i", scalac_returncode)
    sys.exit(1)
  
  # Create output JAR
  if args.outputJar:
    class_files = []
    for root, _, filenames in os.walk(args.buildDir):
      for filename in fnmatch.filter(filenames, '*.class'):
        class_files.append(os.path.relpath(os.path.join(root, filename),
                                           args.buildDir))
    logging.info("Found %i class files", len(class_files))
    logging.debug("Class files: %s", class_files)
    #TODO: check for empty class files
    
    jar_args = ['jar', 'cf', os.path.abspath(args.outputJar)]
    jar_args.extend(class_files)
    
    logging.info("Running jar")
    jar_returncode = subprocess.call(jar_args, cwd=args.buildDir)
    logging.info("jar done")

    if jar_returncode != 0:
      logging.error("jar returned nonzero return code: %i", jar_returncode)
      sys.exit(1)
    