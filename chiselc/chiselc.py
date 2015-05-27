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

import conda.config
import conda.misc

conda_meta_prefix = conda.config.default_prefix+os.sep+'conda-meta'
packages_available = conda.misc.walk_prefix(conda_meta_prefix)
package_by_name={}
for pack in packages_available:
  package_by_name[pack.rsplit('-',2)[0]]=pack

def read_deps(package):
  if package not in package_by_name:
    return []
  with open(conda_meta_prefix+os.sep+package_by_name[package]) as f:
    import json
    j = json.load(f)
    depends = j['depends']
    # these have version information too
    # for now, assume that the only versions in the prefix have been pulled in for me
    # and no other versions exist
    depends = [j.split(' ')[0] for j in depends]
  return depends

# TODO (very far future): support multiple package lists
def resolve_dependencies(packages):
  # do a BFS for dependencies
  this_layer = packages
  next_layer = []
  found = []
  while this_layer:
    for pack in this_layer:
      if pack in found:
        continue
      found.append(pack)
      dep = read_deps(pack)
      if dep is not None:
        next_layer += dep
    this_layer = next_layer
    next_layer = []
  return found

# from conda/cli/main_package.py
def list_package_jars(pkg_name=None):
  import os
  import re
  import conda.config as config
  from conda.misc import walk_prefix

  if pkg_name.endswith('.jar'):
    return [os.path.abspath(pkg_name)]

  pkgs_dirs = config.pkgs_dir_from_envs_dir(conda.config.envs_dirs[0])#config.pkgs_dirs[0]
  all_dir_names = []
  pattern = re.compile(pkg_name, re.I)

  print('\nINFO: The location for available packages: %s' % (pkgs_dirs))

  for dir in os.listdir(pkgs_dirs):
    ignore_dirs = [ '_cache-0.0-x0', 'cache' ]

    if dir in ignore_dirs:
      continue

    if not os.path.isfile(pkgs_dirs+os.sep+dir):
      match = pattern.match(dir)

      if match:
        all_dir_names.append(dir)

  num_of_all_dir_names = len(all_dir_names)
  dir_num_width = len(str(num_of_all_dir_names))

  if num_of_all_dir_names == 0:
    print("\n\tWARN: There is NO '%s' package.\n" % (pkg_name))
    return 1
  elif num_of_all_dir_names >= 2:
    print("\n\tWARN: Ambiguous package name ('%s')\n" % (pkg_name))

  full_pkg_name = all_dir_names[0]
  pkg_dir = pkgs_dirs+os.sep+full_pkg_name
  ret = walk_prefix(pkg_dir, ignore_predefined_files=False)
  return [pkg_dir + os.sep + i for i in ret if i.endswith('.jar')]


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
  parser.add_argument('sourceDirs', nargs='+', default='src/main/scala',
                      help="""list of source directories containing Chisel code,
                            scanned recursively""")
  parser.add_argument('--resourceDirs', nargs='*', default=[],
                      help="""list of resource directories, the contents of
                              which are copied into the resulting JAR""")
  parser.add_argument('--classpath', nargs='*', default=[],
                      help="""dependency JARs to add to the classpath; those
                              sharing the same name as a dependency JAR
                              specified by the package manager will take
                              priority""")
  parser.add_argument('--scalacOpts', nargs='*',  default=['deprecation', 'feature',
                                                           'language:reflectiveCalls',
                                                           'language:implicitConversions',
                                                           'language:existentials'],
                      help="""list of arguments to pass to scalac, in addition
                      to those specified by dependencies""")
  parser.add_argument('-o', '--outputJar', default=None,
                      help="filename and path of output JAR")
  parser.add_argument('-l', '--link', default=[], action='append',
                      help=""""GCC style link against a conda package""")
  parser.add_argument('--linkJars', type=bool, default=True,
                      help="""incorporate the contents of dependency JARs into
                              the output JAR""")
  parser.add_argument('--jarEntryPoint', default=None,
                      help="entrypoint / Main-Class for the JAR")

  args = parser.parse_args(args)

  packages = args.link
  packages_plus_depends = resolve_dependencies(packages)
  logging.debug("Packages including dependencies: %s", packages_plus_depends)

  package_classpaths = []
  for package in packages:
    package_classpath = list_package_jars(package)
    package_classpaths.extend(package_classpath)
    logging.debug("Added classpath for '%s': %s",
                  package, package_classpath)

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


  # Get all the source files
  source_files = []
  for source_dir in args.sourceDirs:
    for root, _, filenames in os.walk(source_dir):
      for filename in fnmatch.filter(filenames, '*.scala'):
        source_files.append(os.path.join(root, filename))
  logging.info("Found %i source files", len(source_files))

  scalac_args = ['scalac']
  scalac_args.extend(source_files)

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

  if args.outputJar:
    scalac_args.extend(['-d', os.path.abspath(args.outputJar)])

  logging.info("Running scalac")
  scalac_returncode = subprocess.call(scalac_args)
  logging.debug("scalac done")

  if scalac_returncode != 0:
    logging.error("scalac returned nonzero return code: %i", scalac_returncode)
    sys.exit(1)

  # Add resources
  for resource_dir in args.resourceDirs:
    logging.info("Copying resources in %s", resource_dir)
    jar_args = ['jar', 'uf', os.path.abspath(args.outputJar),  '-C', resource_dir]
    logging.info("Running jar")
    for root, _, filenames in os.walk(resource_dir):
      for filename in filenames:
        jar_returncode = subprocess.call(jar_args + [filename])
    logging.debug("jar done")

    if jar_returncode != 0:
      logging.error("jar returned nonzero return code: %i", jar_returncode)
      sys.exit(1)

if __name__=="__main__":
  main()
