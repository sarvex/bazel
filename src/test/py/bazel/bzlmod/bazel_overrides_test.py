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


class BazelOverridesTest(test_base.TestBase):

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
    )
    self.ScratchFile(
        '.bazelrc',
        [
            'common --enable_bzlmod',
            f'common --registry={self.main_registry.getURL()}',
            'common --registry=https://bcr.bazel.build',
            'common --verbose_failures',
            'common --java_language_version=8',
            'common --tool_java_language_version=8',
            'common --lockfile_mode=update',
        ],
    )
    self.ScratchFile('WORKSPACE')
    # The existence of WORKSPACE.bzlmod prevents WORKSPACE prefixes or suffixes
    # from being used; this allows us to test built-in modules actually work
    self.ScratchFile('WORKSPACE.bzlmod')

  def writeMainProjectFiles(self):
    self.ScratchFile(
        'aaa.patch',
        [
            '--- a/aaa.cc',
            '+++ b/aaa.cc',
            '@@ -1,6 +1,6 @@',
            ' #include <stdio.h>',
            ' #include "aaa.h"',
            ' void hello_aaa(const std::string& caller) {',
            '-    std::string lib_name = "aaa@1.0";',
            '+    std::string lib_name = "aaa@1.0 (locally patched)";',
            '     printf("%s => %s\\n", caller.c_str(), lib_name.c_str());',
            ' }',
        ],
    )
    self.ScratchFile(
        'BUILD',
        [
            'cc_binary(',
            '  name = "main",',
            '  srcs = ["main.cc"],',
            '  deps = [',
            '    "@aaa//:lib_aaa",',
            '    "@bbb//:lib_bbb",',
            '  ],',
            ')',
        ],
    )
    self.ScratchFile(
        'main.cc',
        [
            '#include "aaa.h"',
            '#include "bbb.h"',
            'int main() {',
            '    hello_aaa("main function");',
            '    hello_bbb("main function");',
            '}',
        ],
    )

  def testSingleVersionOverrideWithPatch(self):
    self.writeMainProjectFiles()
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "aaa", version = "1.1")',
            'bazel_dep(name = "bbb", version = "1.1")',
            # Both main and bbb@1.1 has to depend on the locally patched aaa@1.0
            'single_version_override(',
            '  module_name = "aaa",',
            '  version = "1.0",',
            '  patches = ["//:aaa.patch"],',
            '  patch_strip = 1,',
            ')',
        ],
    )
    _, stdout, _ = self.RunBazel(['run', '//:main'], allow_failure=False)
    self.assertIn('main function => aaa@1.0 (locally patched)', stdout)
    self.assertIn('main function => bbb@1.1', stdout)
    self.assertIn('bbb@1.1 => aaa@1.0 (locally patched)', stdout)

  def testRegistryOverride(self):
    self.writeMainProjectFiles()
    another_registry = BazelRegistry(
        os.path.join(self.registries_work_dir, 'another'),
        ' from another registry',
    )
    another_registry.createCcModule('aaa', '1.0')
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "aaa", version = "1.0")',
            'bazel_dep(name = "bbb", version = "1.0")',
            'single_version_override(',
            '  module_name = "aaa",',
            f'  registry = "{another_registry.getURL()}",',
            ')',
        ],
    )
    _, stdout, _ = self.RunBazel(['run', '//:main'], allow_failure=False)
    self.assertIn('main function => aaa@1.0 from another registry', stdout)
    self.assertIn('main function => bbb@1.0', stdout)
    self.assertIn('bbb@1.0 => aaa@1.0 from another registry', stdout)

  def testArchiveOverride(self):
    self.writeMainProjectFiles()
    archive_aaa_1_0 = self.main_registry.archives.joinpath('aaa.1.0.zip')
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "aaa", version = "1.1")',
            'bazel_dep(name = "bbb", version = "1.1")',
            'archive_override(',
            '  module_name = "aaa",',
            f'  urls = ["{archive_aaa_1_0.as_uri()}"],',
            '  patches = ["//:aaa.patch"],',
            '  patch_strip = 1,',
            ')',
        ],
    )
    _, stdout, _ = self.RunBazel(['run', '//:main'], allow_failure=False)
    self.assertIn('main function => aaa@1.0 (locally patched)', stdout)
    self.assertIn('main function => bbb@1.1', stdout)
    self.assertIn('bbb@1.1 => aaa@1.0 (locally patched)', stdout)

  def testGitOverride(self):
    self.writeMainProjectFiles()
    src_aaa_1_0 = self.main_registry.projects.joinpath('aaa', '1.0')
    self.RunProgram(['git', 'init'], cwd=src_aaa_1_0, allow_failure=False)
    self.RunProgram(
        ['git', 'config', 'user.name', 'tester'],
        cwd=src_aaa_1_0,
        allow_failure=False,
    )
    self.RunProgram(
        ['git', 'config', 'user.email', 'tester@foo.com'],
        cwd=src_aaa_1_0,
        allow_failure=False,
    )
    self.RunProgram(['git', 'add', './'], cwd=src_aaa_1_0, allow_failure=False)
    self.RunProgram(
        ['git', 'commit', '-m', 'Initial commit.'],
        cwd=src_aaa_1_0,
        allow_failure=False,
    )
    _, stdout, _ = self.RunProgram(
        ['git', 'rev-parse', 'HEAD'], cwd=src_aaa_1_0, allow_failure=False
    )
    commit = stdout[0].strip()

    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "aaa", version = "1.1")',
            'bazel_dep(name = "bbb", version = "1.1")',
            'git_override(',
            '  module_name = "aaa",',
            f'  remote = "{src_aaa_1_0.as_uri()}",',
            f'  commit = "{commit}",',
            '  patches = ["//:aaa.patch"],',
            '  patch_strip = 1,',
            ')',
        ],
    )
    _, stdout, _ = self.RunBazel(['run', '//:main'], allow_failure=False)
    self.assertIn('main function => aaa@1.0 (locally patched)', stdout)
    self.assertIn('main function => bbb@1.1', stdout)
    self.assertIn('bbb@1.1 => aaa@1.0 (locally patched)', stdout)

  def testLocalPathOverride(self):
    src_aaa_1_0 = self.main_registry.projects.joinpath('aaa', '1.0')
    self.writeMainProjectFiles()
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "aaa", version = "1.1")',
            'bazel_dep(name = "bbb", version = "1.1")',
            'local_path_override(',
            '  module_name = "aaa",',
            '  path = "%s",' % str(src_aaa_1_0.resolve()).replace('\\', '/'),
            ')',
        ],
    )
    _, stdout, _ = self.RunBazel(['run', '//:main'], allow_failure=False)
    self.assertIn('main function => aaa@1.0', stdout)
    self.assertIn('main function => bbb@1.1', stdout)
    self.assertIn('bbb@1.1 => aaa@1.0', stdout)

  def testCmdAbsoluteModuleOverride(self):
    # test commandline_overrides takes precedence over local_path_override
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "ss", version = "1.0")',
            'local_path_override(',
            '  module_name = "ss",',
            f"""  path = "{self.Path('aa')}",""",
            ')',
        ],
    )
    self.ScratchFile('BUILD')
    self.ScratchFile('WORKSPACE')

    self.ScratchFile(
        'aa/MODULE.bazel',
        [
            "module(name='ss')",
        ],
    )
    self.ScratchFile(
        'aa/BUILD',
        [
            'filegroup(name = "never_ever")',
        ],
    )
    self.ScratchFile('aa/WORKSPACE')

    self.ScratchFile(
        'bb/MODULE.bazel',
        [
            "module(name='ss')",
        ],
    )
    self.ScratchFile(
        'bb/BUILD',
        [
            'filegroup(name = "choose_me")',
        ],
    )
    self.ScratchFile('bb/WORKSPACE')

    _, _, stderr = self.RunBazel(
        ['build', '@ss//:all', '--override_module', 'ss=' + self.Path('bb')],
        allow_failure=False,
    )
    # module file override should be ignored, and bb directory should be used
    self.assertIn(
        'Target @ss~override//:choose_me up-to-date (nothing to build)', stderr
    )

  def testCmdRelativeModuleOverride(self):
    self.ScratchFile('aa/WORKSPACE')
    self.ScratchFile(
        'aa/MODULE.bazel',
        [
            'bazel_dep(name = "ss", version = "1.0")',
        ],
    )
    self.ScratchFile('aa/BUILD')

    self.ScratchFile('aa/cc/BUILD')

    self.ScratchFile('bb/WORKSPACE')
    self.ScratchFile(
        'bb/MODULE.bazel',
        [
            'module(name="ss")',
        ],
    )
    self.ScratchFile(
        'bb/BUILD',
        [
            'filegroup(name = "choose_me")',
        ],
    )

    _, _, stderr = self.RunBazel(
        [
            'build',
            '@ss//:all',
            '--override_module',
            'ss=../../bb',
            '--enable_bzlmod',
        ],
        cwd=self.Path('aa/cc'),
        allow_failure=False,
    )
    self.assertIn(
        'Target @ss~override//:choose_me up-to-date (nothing to build)', stderr
    )

  def testCmdWorkspaceRelativeModuleOverride(self):
    self.ScratchFile('WORKSPACE')
    self.ScratchFile(
        'MODULE.bazel',
        [
            'bazel_dep(name = "ss", version = "1.0")',
        ],
    )
    self.ScratchFile('BUILD')
    self.ScratchFile('aa/BUILD')
    self.ScratchFile('bb/WORKSPACE')
    self.ScratchFile(
        'bb/MODULE.bazel',
        [
            'module(name="ss")',
        ],
    )
    self.ScratchFile(
        'bb/BUILD',
        [
            'filegroup(name = "choose_me")',
        ],
    )

    _, _, stderr = self.RunBazel(
        [
            'build',
            '@ss//:all',
            '--override_module',
            'ss=%workspace%/bb',
        ],
        cwd=self.Path('aa'),
        allow_failure=False,
    )
    self.assertIn(
        'Target @ss~override//:choose_me up-to-date (nothing to build)', stderr
    )


if __name__ == '__main__':
  unittest.main()
