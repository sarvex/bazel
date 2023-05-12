# pylint: disable=invalid-name
# pylint: disable=g-long-ternary
# Copyright 2021 The Bazel Authors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Test utils for Bzlmod."""

import base64
import hashlib
import json
import os
import pathlib
import shutil
import urllib.request
import zipfile


def download(url):
  """Download a file and return its content in bytes."""
  response = urllib.request.urlopen(url)
  return response.read()


def read(path):
  """Read a file and return its content in bytes."""
  with open(str(path), 'rb') as f:
    return f.read()


def integrity(data):
  """Calculate the integration value of the data with sha256."""
  hash_value = hashlib.sha256(data)
  return f'sha256-{base64.b64encode(hash_value.digest()).decode()}'


def scratchFile(path, lines=None):
  """Creates a file at the given path with the given content."""
  with open(str(path), 'w') as f:
    if lines:
      for l in lines:
        f.write(l)
        f.write('\n')


class Module:
  """A class to represent information of a Bazel module."""

  def __init__(self, name, version):
    self.name = name
    self.version = version
    self.archive_url = None
    self.strip_prefix = ''
    self.module_dot_bazel = None
    self.patches = []
    self.patch_strip = 0
    self.archive_type = None

  def set_source(self, archive_url, strip_prefix=None):
    self.archive_url = archive_url
    self.strip_prefix = strip_prefix
    return self

  def set_module_dot_bazel(self, module_dot_bazel):
    self.module_dot_bazel = module_dot_bazel
    return self

  def set_patches(self, patches, patch_strip):
    self.patches = patches
    self.patch_strip = patch_strip
    return self

  def set_archive_type(self, archive_type):
    self.archive_type = archive_type
    return self


class BazelRegistry:
  """A class to help create a Bazel module project from scatch and add it into the registry."""

  def __init__(self, root, registry_suffix=''):
    self.root = pathlib.Path(root)
    self.projects = self.root.joinpath('projects')
    self.projects.mkdir(parents=True, exist_ok=True)
    self.archives = self.root.joinpath('archives')
    self.archives.mkdir(parents=True, exist_ok=True)
    self.registry_suffix = registry_suffix

  def setModuleBasePath(self, module_base_path):
    bazel_registry = {
        'module_base_path': module_base_path,
    }
    with self.root.joinpath('bazel_registry.json').open('w') as f:
      json.dump(bazel_registry, f, indent=4, sort_keys=True)

  def getURL(self):
    """Return the URL of this registry."""
    return self.root.resolve().as_uri()

  def generateCcSource(self, name, version, deps=None, repo_names=None):
    """Generate a cc project with given dependency information.

    1. The cc projects implements a hello_<lib_name> function.
    2. The hello_<lib_name> function calls the same function of its
    dependencies.
    3. The hello_<lib_name> function prints "<caller name> =>
    <lib_name@version>".
    4. The BUILD file references the dependencies as their desired repo names.

    Args:
      name:  The module name.
      version: The module version.
      deps: The dependencies of this module.
      repo_names: The desired repository name for some dependencies.

    Returns:
      The generated source directory.
    """

    src_dir = self.projects.joinpath(name, version)
    src_dir.mkdir(parents=True, exist_ok=True)
    if not deps:
      deps = {}
    if not repo_names:
      repo_names = {}
    for dep in deps:
      if dep not in repo_names:
        repo_names[dep] = dep

    def calc_repo_name_str(dep):
      return '' if dep == repo_names[dep] else f', repo_name = "{repo_names[dep]}"'

    scratchFile(src_dir.joinpath('WORKSPACE'))
    scratchFile(
        src_dir.joinpath('MODULE.bazel'),
        ([
            'module(',
            f'  name = "{name}",',
            f'  version = "{version}",',
            '  compatibility_level = 1,',
            ')',
        ] + [
            f'bazel_dep(name = "{dep}", version = "{version}"{calc_repo_name_str(dep)})'
            for dep, version in deps.items()
        ]),
    )

    scratchFile(
        src_dir.joinpath(f'{name.lower()}.h'),
        [
            f'#ifndef {name.upper()}_H',
            f'#define {name.upper()}_H',
            '#include <string>',
            f'void hello_{name.lower()}(const std::string& caller);',
            '#endif',
        ],
    )
    scratchFile(
        src_dir.joinpath(f'{name.lower()}.cc'),
        ((((['#include <stdio.h>', f'#include "{name.lower()}.h"'] + [
            f'#include "{dep.lower()}.h"' for dep in deps
        ]) + [
            'void hello_%s(const std::string& caller) {' % name.lower(),
            f'    std::string lib_name = "{name}@{version}{self.registry_suffix}";',
            '    printf("%s => %s\\n", caller.c_str(), lib_name.c_str());',
        ]) + [f'    hello_{dep.lower()}(lib_name);' for dep in deps]) + [
            '}',
        ]),
    )
    scratchFile(
        src_dir.joinpath('BUILD'),
        (([
            'package(default_visibility = ["//visibility:public"])',
            'cc_library(',
            f'  name = "lib_{name.lower()}",',
            f'  srcs = ["{name.lower()}.cc"],',
            f'  hdrs = ["{name.lower()}.h"],',
        ] + ([('  deps = ["%s"],' % '", "'.join(
            [f'@{repo_names[dep]}//:lib_{dep.lower()}'
             for dep in deps]))] if deps else [])) + [
                 ')',
             ]),
    )
    return src_dir

  def createArchive(self, name, version, src_dir, filename_pattern='%s.%s.zip'):
    """Create an archive with a given source directory."""
    zip_path = self.archives.joinpath(filename_pattern % (name, version))
    zip_obj = zipfile.ZipFile(str(zip_path), 'w')
    for foldername, _, filenames in os.walk(str(src_dir)):
      for filename in filenames:
        filepath = os.path.join(foldername, filename)
        zip_obj.write(filepath,
                      str(pathlib.Path(filepath).relative_to(src_dir)))
    zip_obj.close()
    return zip_path

  def addModule(self, module):
    """Add a module into the registry."""
    module_dir = self.root.joinpath('modules', module.name, module.version)
    module_dir.mkdir(parents=True, exist_ok=True)

    # Copy MODULE.bazel to the registry
    module_dot_bazel = module_dir.joinpath('MODULE.bazel')
    shutil.copy(str(module.module_dot_bazel), str(module_dot_bazel))

    # Create source.json & copy patch files to the registry
    source = {
        'url': module.archive_url,
        'integrity': integrity(download(module.archive_url)),
    }
    if module.strip_prefix:
      source['strip_prefix'] = module.strip_prefix

    if module.patches:
      patch_dir = module_dir.joinpath('patches')
      patch_dir.mkdir()
      source['patches'] = {}
      source['patch_strip'] = module.patch_strip
      for patch_path in module.patches:
        patch = pathlib.Path(patch_path)
        source['patches'][patch.name] = integrity(read(patch))
        shutil.copy(str(patch), str(patch_dir))

    if module.archive_type:
      source['archive_type'] = module.archive_type

    with module_dir.joinpath('source.json').open('w') as f:
      json.dump(source, f, indent=4, sort_keys=True)

  def createCcModule(
      self,
      name,
      version,
      deps=None,
      repo_names=None,
      patches=None,
      patch_strip=0,
      archive_pattern=None,
      archive_type=None,
  ):
    """Generate a cc project and add it as a module into the registry."""
    src_dir = self.generateCcSource(name, version, deps, repo_names)
    if archive_pattern:
      archive = self.createArchive(
          name, version, src_dir, filename_pattern=archive_pattern
      )
    else:
      archive = self.createArchive(name, version, src_dir)
    module = Module(name, version)
    module.set_source(archive.resolve().as_uri())
    module.set_module_dot_bazel(src_dir.joinpath('MODULE.bazel'))
    if patches:
      module.set_patches(patches, patch_strip)
    if archive_type:
      module.set_archive_type(archive_type)

    self.addModule(module)
    return self

  def addMetadata(self,
                  name,
                  homepage=None,
                  maintainers=None,
                  versions=None,
                  yanked_versions=None):
    """Generate a module metadata file and add it to the registry."""
    if maintainers is None:
      maintainers = []
    if versions is None:
      versions = []
    if yanked_versions is None:
      yanked_versions = {}

    module_dir = self.root.joinpath('modules', name)
    module_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        'homepage': homepage,
        'maintainers': maintainers,
        'versions': versions,
        'yanked_versions': yanked_versions
    }

    with module_dir.joinpath('metadata.json').open('w') as f:
      json.dump(metadata, f, indent=4, sort_keys=True)

    return self

  def createLocalPathModule(self, name, version, path, deps=None):
    """Add a local module into the registry."""
    module_dir = self.root.joinpath('modules', name, version)
    module_dir.mkdir(parents=True, exist_ok=True)

    # Create source.json & copy patch files to the registry
    source = {
        'type': 'local_path',
        'path': path,
    }

    if deps is None:
      deps = {}

    scratchFile(
        module_dir.joinpath('MODULE.bazel'),
        (['module(', f'  name = "{name}",', f'  version = "{version}",', ')'] +
         ['bazel_dep(name="%s",version="%s")' % p for p in deps.items()]),
    )

    with module_dir.joinpath('source.json').open('w') as f:
      json.dump(source, f, indent=4, sort_keys=True)
