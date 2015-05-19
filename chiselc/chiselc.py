#!/usr/bin/env python

import argparse
import errno
import fnmatch
import logging
import os
import re
import shutil
import subprocess
import sys

def parse_portage_depends(depends_string):
  depends_list = depends_string.split()
  out_list = []
  for depend in depends_list:
    # for now, require an explicit version to make implementation easier
    if not depend.startswith('='):
      raise NotImplementedError("Portage dependencies must have versions explicitly specified, '%s' is not yet supported" % depend)
    out_list.append(depend[1:])
  return out_list

class Package(object):
  """A package definition object
  """
  def get_pkgname(self):
    """Returns the package name, a globally unique identifier which consists of
    the name and the version number.
    """
    raise NotImplementedError()

  def get_dependencies(self):
    """Returns dependencies as a list of Packages.
    """
    raise NotImplementedError()

  def get_field(self, fieldname, include_private=True):
    """Returns the value of an arbitrary field"""
    raise NotImplementedError()

class PackageCollection(object):
  """Abstract base class for package collections, a listing of installed
  packages.
  """
  def get_package(self, package_name):
    """Returns the argument package as a Package object, or None if it doesn't
    exist.
    """
    raise NotImplementedError()

class PortagePkgList(PackageCollection):
  """Installed package for Portage.
  """
  def __init__(self, pkgdb_path, pkgjar_path):
    self.pkgdb_path = pkgdb_path
    self.pkgjar_path = pkgjar_path

  def get_package(self, package_name):
    """Returns the argument package as a Package object, or None if it doesn't
    exist.
    """
    return PortageInstalledPackage(self, package_name)

class PortageInstalledPackage(Package):
  """Package collection for Portage, usually under /var/db/pkg.
  """
  def __init__(self, pkglist, package_name):
    self.pkglist = pkglist
    self.package_name = package_name
    self.pkgdb_path = os.path.join(pkglist.pkgdb_path, package_name)
    if not os.path.isdir(self.pkgdb_path):
      logging.error("Package '%s' isn't installed (can't find %s)",
                    package_name, self.pkgdb_path)
      sys.exit(1)

    self.ebuild_vars = {}
    ebuild_filepath = os.path.join(self.pkglist.pkgdb_path, self.package_name,
                                   self.get_noncategory_pkgname() + ".ebuild")
    with open(ebuild_filepath, "r") as ebuild_file:
      for ebuild_line in ebuild_file:
        match = re.match(r'^\s*([^=\s])+\s*=\s*"([^"]*)\s*$"', ebuild_line)
        if match:
          var_name = match.group(1)
          if var_name in self.ebuild_vars:
            logging.error("Package '%s' has variable '%s' defined twice",
                          package_name, var_name)
            sys.exit(1)
          self.ebuild_vars[var_name] = match.group(2).split()

    # TODO: add versioning constraints, defaulting at least
    # right now, assume version is specified as part of package name

  def get_pkgname(self):
    return self.package_name

  def get_noncategory_pkgname(self):
      sep = self.get_pkgname().rfind("/")
      # TODO: error checking here
      return self.get_pkgname()[sep+1:]

  def get_dependencies(self):
    if 'CHISEL_LIBRARY_DEPENDENCIES' in self.ebuild_vars:
      return self.ebuild_vars['CHISEL_LIBRARY_DEPENDENCIES']
    else:
      return []

    depends_filepath = os.path.join(self.pkglist.pkgdb_path, self.package_name,
                                    "DEPEND")
    if not os.path.exists(depends_filepath):
      return []
    with open(depends_filepath, "r") as depends_file:
      depends_list = parse_portage_depends(depends_file.read())
      return [self.pkglist.get_package(package_name) for package_name in depends_list]

  def get_field(self, fieldname):
    if fieldname == 'classpath':
      return [os.path.join(self.pkglist.pkgjar_path,
                           self.get_noncategory_pkgname() + ".jar")]
    else:
      raise NotImplementedError("Unknown field '%s'" % fieldname)

def copy_dir(src, dst):
  """Copies the contents of the directory src and places them in an already
  existing directory dst."""
  assert os.path.exists(src)
  assert os.path.exists(dst)

  for filename in os.listdir(src):
    try:
      # TODO: check and ensure dst does not exist?
      shutil.copytree(os.path.join(src, filename),
                      os.path.join(dst, filename))
    except OSError as e:
      if e.errno == errno.ENOTDIR:
        shutil.copy(os.path.join(src, filename),
                    os.path.join(dst, filename))
      else:
        raise e

def main(args=None):
  if args is None:
    args = sys.argv[1:]

  logging.basicConfig(level=logging.INFO)
  logger = logging.getLogger(__name__)

  parser = argparse.ArgumentParser(description="Chisel compiler wrapper script")
  parser.add_argument('sourceDirs', nargs='+',
                      help="""list of source directories containing Chisel code,
                            scanned recursively""")
  parser.add_argument('buildDir',
                      help="working directory to place build output files")
  parser.add_argument('--resourceDirs', nargs='*', default=[],
                      help="""list of resource directories, the contents of
                              which are copied into the resulting JAR""")
  parser.add_argument('--portagePkgDepends',
                      help="""Portage DEPENDS-style list of dependencies""")
  parser.add_argument('--portagePkgDbDir',
                      help="""directory with Portage installed package
                              definition files and contents, used when resolving
                              dependencies""")
  parser.add_argument('--portagePkgJarDir',
                      help="""directory where installed Chisel package jars are
                              stored""")
  parser.add_argument('--classpath', nargs='*', default=[],
                      help="""dependency JARs to add to the classpath; those
                              sharing the same name as a dependency JAR
                              specified by the package manager will take
                              priority""")
  parser.add_argument('--scalacOpts', nargs='*',  default=[],
                      help="""list of arguments to pass to scalac, in addition
                      to those specified by dependencies""")
  parser.add_argument('--outputJar', default=None,
                      help="filename and path of output JAR")
  parser.add_argument('--linkJars', type=bool, default=True,
                      help="""incorporate the contents of dependency JARs into
                              the output JAR""")
  parser.add_argument('--jarEntryPoint', default=None,
                      help="entrypoint / Main-Class for the JAR")

  args = parser.parse_args(args)

  compile_dir = args.buildDir

  package_collection = PortagePkgList(args.portagePkgDbDir,
                                      args.portagePkgJarDir)
  packages = []

  # TODO (very far future): support multiple package lists
  package_dependencies = parse_portage_depends(args.portagePkgDepends)
  logging.debug("Found immediate dependencies: %s", package_dependencies)
  for dep_pkgname in package_dependencies:
    packages.append(package_collection.get_package(dep_pkgname))


  package_classpaths = []
  for package in packages:
    package_classpath = package.get_field('classpath')
    package_classpaths.extend(package_classpath)
    logging.debug("Added classpath for '%s': %s",
                  package.get_pkgname(), package_classpath)

  # Add override classpaths from command line arguments
  classpaths = []
  classpaths_args_basenames = [os.path.basename(classpath)
                               for classpath in args.classpath]
  for package_classpath in package_classpaths:
    if os.path.basename(package_classpath) in classpaths_args_basenames:
      logging.info("Dropping package classpath %s (overridden by --classpath argument)", package_classpath)
    else:
      classpaths.append(package_classpath)

  classpaths.extend([os.path.abspath(classpath)
                     for classpath in args.classpath])

  # TODO: perhaps require that this directory is empty?
  if not os.path.exists(compile_dir):
    os.makedirs(compile_dir)

  if args.linkJars and args.outputJar:
    # Extract all dependency JARs to working directory
    # TODO: check for conflicting files
    for classpathJar in classpaths:
      jar_args = ['jar', 'xf', classpathJar]
      logging.info("Extracting dependency %s with jar", classpathJar)
      jar_returncode = subprocess.call(jar_args, cwd=compile_dir)
      logging.debug("Extraction done")
      if jar_returncode != 0:
        logging.error("jar returned nonzero return code: %i", jar_returncode)
        sys.exit(1)

  for resource_dir in args.resourceDirs:
    logging.info("Copying resources in %s", resource_dir)
    copy_dir(resource_dir, compile_dir)

  # Get all the source files
  source_files = []
  for source_dir in args.sourceDirs:
    for root, _, filenames in os.walk(source_dir):
      for filename in fnmatch.filter(filenames, '*.scala'):
        source_files.append(os.path.join(root, filename))
  logging.info("Found %i source files", len(source_files))

  scalac_args = ['scalac']
  scalac_args.extend(source_files)
  scalac_args.extend(['-d', os.path.abspath(compile_dir)])

  scalacopts = args.scalacOpts
  scalacopts = ["-" + scalacopt for scalacopt in scalacopts]
  if scalacopts:
    logging.debug("Using scalacopts: %s", scalacopts)
    scalac_args.extend(scalacopts)

  if classpaths:
    for classpath in classpaths:
      if not os.path.exists(classpath):
        logging.error("Required classpath %s doesn't exist", classpath)
    # TODO: support Windows OS (uses semicolon for classpath separator)
    classpath_str = ':'.join(classpaths)

    logging.debug("Using classpath: %s", classpath_str)
    scalac_args.extend(['-classpath', classpath_str])

  logging.info("Running scalac")
  scalac_returncode = subprocess.call(scalac_args)
  logging.debug("scalac done")

  if scalac_returncode != 0:
    logging.error("scalac returned nonzero return code: %i", scalac_returncode)
    sys.exit(1)

  # Create output JAR
  if args.outputJar:
    class_files = []
    for root, _, filenames in os.walk(compile_dir):
      for filename in filenames:
        class_files.append(os.path.relpath(os.path.join(root, filename),
                                           compile_dir))
    logging.info("Found %i class files", len(class_files))
    logging.debug("Class files: %s", class_files)
    #TODO: check for empty class files

    if args.jarEntryPoint:
      jar_args = ['jar', 'cfe', os.path.abspath(args.outputJar),
                  args.jarEntryPoint]
    else:
      jar_args = ['jar', 'cf', os.path.abspath(args.outputJar)]
    jar_args.extend(class_files)

    logging.info("Running jar")
    jar_returncode = subprocess.call(jar_args, cwd=compile_dir)
    logging.debug("jar done")

    if jar_returncode != 0:
      logging.error("jar returned nonzero return code: %i", jar_returncode)
      sys.exit(1)

if __name__=="__main__":
  main()