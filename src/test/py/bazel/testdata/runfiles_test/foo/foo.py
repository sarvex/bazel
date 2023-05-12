# Copyright 2018 The Bazel Authors. All rights reserved.
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
"""Mock Python binary, only used in tests."""

from __future__ import print_function

import os
import subprocess

from bazel_tools.tools.python.runfiles import runfiles


def IsWindows():
  return os.name == "nt"


def ChildBinaryName(lang):
  if IsWindows():
    return f"foo_ws/bar/bar-{lang}.exe"
  else:
    return f"foo_ws/bar/bar-{lang}"


def SplitToLines(stdouterr):
  if isinstance(stdouterr, bytes):
    # Python3's communicate() returns bytes.
    return [l.strip() for l in stdouterr.decode().split("\n")]
  else:
    # Python2's communicate() returns str.
    return [l.strip() for l in stdouterr.split("\n")]


def main():
  print("Hello Python Foo!")
  r = runfiles.Create()
  print(f'rloc={r.Rlocation("foo_ws/foo/datadep/hello.txt")}')

  # Run a subprocess, propagate the runfiles envvar to it. The subprocess will
  # use this process's runfiles manifest or runfiles directory.
  env = {"SYSTEMROOT": os.environ["SYSTEMROOT"]} if IsWindows() else {}
  env |= r.EnvVars()
  for lang in ["py", "java", "sh", "cc"]:
    p = subprocess.Popen(
        [r.Rlocation(ChildBinaryName(lang))],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE)
    out, err = p.communicate()
    out = SplitToLines(out)
    if len(out) < 2:
      raise Exception(f"ERROR: error running bar-{lang}: {SplitToLines(err)}")
    print(out[0])  # e.g. "Hello Python Bar!"
    print(out[1])  # e.g. "rloc=/tmp/foo_ws/bar/bar-py-data.txt"


if __name__ == "__main__":
  main()
