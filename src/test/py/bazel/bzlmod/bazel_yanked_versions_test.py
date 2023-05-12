# pylint: disable=g-backslash-continuation
# Copyright 2023 The Bazel Authors. All rights reserved.
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
# pylint: disable=g-long-ternary

import os
import tempfile
import unittest

from src.test.py.bazel import test_base
from src.test.py.bazel.bzlmod.test_utils import BazelRegistry


class BazelYankedVersionsTest(test_base.TestBase):

  def setUp(self):
    test_base.TestBase.setUp(self)
    self.registries_work_dir = tempfile.mkdtemp(dir=self._test_cwd)
    self.main_registry = BazelRegistry(
        os.path.join(self.registries_work_dir, 'main')
    )
    self.main_registry.createCcModule('aaa', '1.0').createCcModule(
        'aaa', '1.1'
    ).createCcModule('bbb', '1.0', {'aaa': '1.0'}).createCcModule(
        'bbb', '1.1', {'aaa': '1.1'}
    ).createCcModule(
        'ccc', '1.1', {'aaa': '1.1', 'bbb': '1.1'}
    ).createCcModule(
        'ddd', '1.0', {'yanked1': '1.0', 'yanked2': '1.0'}
    ).createCcModule(
        'eee', '1.0', {'yanked1': '1.0'}
    ).createCcModule(
        'yanked1', '1.0'
    ).createCcModule(
        'yanked2', '1.0'
    ).addMetadata(
        'yanked1', yanked_versions={'1.0': 'dodgy'}
    ).addMetadata(
        'yanked2', yanked_versions={'1.0': 'sketchy'}
    )
    self.writeBazelrcFile()
    self.ScratchFile('WORKSPACE')
    # The existence of WORKSPACE.bzlmod prevents WORKSPACE prefixes or suffixes
    # from being used; this allows us to test built-in modules actually work
    self.ScratchFile('WORKSPACE.bzlmod')

  def writeBazelrcFile(self, allow_yanked_versions=True):
    self.ScratchFile(
        '.bazelrc',
        ([
            'common --enable_bzlmod',
            f'common --registry={self.main_registry.getURL()}',
            'common --registry=https://bcr.bazel.build',
            'common --verbose_failures',
            'common --java_language_version=8',
            'common --tool_java_language_version=8',
            'common --lockfile_mode=update',
        ] + ([
            # Disable yanked version check so we are not affected BCR
            # changes.
            'common --allow_yanked_versions=all',
        ] if allow_yanked_versions else [])),
    )

  def testNonRegistryOverriddenModulesIgnoreYanked(self):
    self.writeBazelrcFile(allow_yanked_versions=False)
    src_yanked1 = self.main_registry.projects.joinpath('yanked1', '1.0')
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "yanked1", version = "1.0")',
            'local_path_override(',
            '  module_name = "yanked1",',
            '  path = "%s",' % str(src_yanked1.resolve()).replace('\\', '/'),
            ')',
        ],
    )
    self.ScratchFile('WORKSPACE')
    self.ScratchFile(
        'BUILD',
        [
            'cc_binary(',
            '  name = "main",',
            '  srcs = ["main.cc"],',
            '  deps = ["@yanked1//:lib_yanked1"],',
            ')',
        ],
    )
    self.RunBazel(['build', '--nobuild', '//:main'], allow_failure=False)

  def testContainingYankedDepFails(self):
    self.writeBazelrcFile(allow_yanked_versions=False)
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "yanked1", version = "1.0")',
        ],
    )
    self.ScratchFile('WORKSPACE')
    self.ScratchFile(
        'BUILD',
        [
            'cc_binary(',
            '  name = "main",',
            '  srcs = ["main.cc"],',
            '  deps = ["@ddd//:lib_ddd"],',
            ')',
        ],
    )
    exit_code, _, stderr = self.RunBazel(
        ['build', '--nobuild', '//:main'], allow_failure=True
    )
    self.AssertExitCode(exit_code, 48, stderr)
    self.assertIn(
        'Yanked version detected in your resolved dependency graph: '
        + 'yanked1@1.0, for the reason: dodgy.',
        ''.join(stderr),
    )

  def testAllowedYankedDepsSuccessByFlag(self):
    self.writeBazelrcFile(allow_yanked_versions=False)
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "ddd", version = "1.0")',
        ],
    )
    self.ScratchFile('WORKSPACE')
    self.ScratchFile(
        'BUILD',
        [
            'cc_binary(',
            '  name = "main",',
            '  srcs = ["main.cc"],',
            '  deps = ["@ddd//:lib_ddd"],',
            ')',
        ],
    )
    self.RunBazel(
        [
            'build',
            '--nobuild',
            '--allow_yanked_versions=yanked1@1.0,yanked2@1.0',
            '//:main',
        ],
        allow_failure=False,
    )

  def testAllowedYankedDepsByEnvVar(self):
    self.writeBazelrcFile(allow_yanked_versions=False)
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "ddd", version = "1.0")',
        ],
    )
    self.ScratchFile('WORKSPACE')
    self.ScratchFile(
        'BUILD',
        [
            'cc_binary(',
            '  name = "main",',
            '  srcs = ["main.cc"],',
            '  deps = ["@ddd//:lib_ddd"],',
            ')',
        ],
    )
    self.RunBazel(
        ['build', '--nobuild', '//:main'],
        env_add={'BZLMOD_ALLOW_YANKED_VERSIONS': 'yanked1@1.0,yanked2@1.0'},
        allow_failure=False,
    )

    # Test changing the env var, the build should fail again.
    exit_code, _, stderr = self.RunBazel(
        ['build', '--nobuild', '//:main'],
        env_add={'BZLMOD_ALLOW_YANKED_VERSIONS': 'yanked2@1.0'},
        allow_failure=True,
    )
    self.AssertExitCode(exit_code, 48, stderr)
    self.assertIn(
        'Yanked version detected in your resolved dependency graph: '
        + 'yanked1@1.0, for the reason: dodgy.',
        ''.join(stderr),
    )

  def testAllowedYankedDepsSuccessMix(self):
    self.writeBazelrcFile(allow_yanked_versions=False)
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "ddd", version = "1.0")',
        ],
    )
    self.ScratchFile('WORKSPACE')
    self.ScratchFile(
        'BUILD',
        [
            'cc_binary(',
            '  name = "main",',
            '  srcs = ["main.cc"],',
            '  deps = ["@ddd//:lib_ddd"],',
            ')',
        ],
    )
    self.RunBazel(
        [
            'build',
            '--nobuild',
            '--allow_yanked_versions=yanked1@1.0',
            '//:main',
        ],
        env_add={'BZLMOD_ALLOW_YANKED_VERSIONS': 'yanked2@1.0'},
        allow_failure=False,
    )


if __name__ == '__main__':
  unittest.main()
