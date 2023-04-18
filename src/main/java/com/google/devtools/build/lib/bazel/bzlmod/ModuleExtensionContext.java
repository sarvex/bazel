// Copyright 2021 The Bazel Authors. All rights reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//    http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package com.google.devtools.build.lib.bazel.bzlmod;

import com.google.common.collect.ImmutableMap;
import com.google.devtools.build.docgen.annot.DocCategory;
import com.google.devtools.build.lib.bazel.repository.downloader.DownloadManager;
import com.google.devtools.build.lib.bazel.repository.starlark.StarlarkBaseExternalContext;
import com.google.devtools.build.lib.runtime.ProcessWrapper;
import com.google.devtools.build.lib.runtime.RepositoryRemoteExecutor;
import com.google.devtools.build.lib.vfs.Path;
import com.google.devtools.build.skyframe.SkyFunction.Environment;
import java.util.Map;
import javax.annotation.Nullable;
import net.starlark.java.annot.Param;
import net.starlark.java.annot.ParamType;
import net.starlark.java.annot.StarlarkBuiltin;
import net.starlark.java.annot.StarlarkMethod;
import net.starlark.java.eval.EvalException;
import net.starlark.java.eval.NoneType;
import net.starlark.java.eval.Sequence;
import net.starlark.java.eval.StarlarkList;
import net.starlark.java.eval.StarlarkSemantics;

/** The Starlark object passed to the implementation function of module extensions. */
@StarlarkBuiltin(
    name = "module_ctx",
    category = DocCategory.BUILTIN,
    doc =
        "The context of the module extension containing helper functions and information about"
            + " pertinent tags across the dependency graph. You get a module_ctx object as an"
            + " argument to the <code>implementation</code> function when you create a module"
            + " extension.")
public class ModuleExtensionContext extends StarlarkBaseExternalContext {
  private final ModuleExtensionId extensionId;
  private final StarlarkList<StarlarkBazelModule> modules;

  protected ModuleExtensionContext(
      Path workingDirectory,
      Environment env,
      Map<String, String> envVariables,
      DownloadManager downloadManager,
      double timeoutScaling,
      @Nullable ProcessWrapper processWrapper,
      StarlarkSemantics starlarkSemantics,
      @Nullable RepositoryRemoteExecutor remoteExecutor,
      ModuleExtensionId extensionId,
      StarlarkList<StarlarkBazelModule> modules) {
    super(
        workingDirectory,
        env,
        envVariables,
        downloadManager,
        timeoutScaling,
        processWrapper,
        starlarkSemantics,
        remoteExecutor);
    this.extensionId = extensionId;
    this.modules = modules;
  }

  public Path getWorkingDirectory() {
    return workingDirectory;
  }

  @Override
  protected String getIdentifyingStringForLogging() {
    return String.format(
        "module extension %s in %s", extensionId.getExtensionName(), extensionId.getBzlFileLabel());
  }

  @Override
  protected boolean isRemotable() {
    // Maybe we can some day support remote execution, but not today.
    return false;
  }

  @Override
  protected ImmutableMap<String, String> getRemoteExecProperties() throws EvalException {
    return ImmutableMap.of();
  }

  @StarlarkMethod(
      name = "modules",
      structField = true,
      doc =
          "A list of all the Bazel modules in the external dependency graph, each of which is a <a"
              + " href=\"../builtins/bazel_module.html\">bazel_module</a> object that exposes all"
              + " the tags it specified for this module extension. The iteration order of this"
              + " dictionary is guaranteed to be the same as breadth-first search starting from the"
              + " root module.")
  public StarlarkList<StarlarkBazelModule> getModules() {
    return modules;
  }

  @StarlarkMethod(
      name = "is_dev_dependency",
      doc =
          "Returns whether the given tag was specified on the result of a <a "
              + "href=\"../globals/module.html#use_extension\">use_extension</a> call with "
              + "<code>devDependency = True</code>.",
      parameters = {
        @Param(
            name = "tag",
            doc =
                "A tag obtained from <a"
                    + " href=\"../builtins/bazel_module.html#tags\">bazel_module.tags</a>.",
            allowedTypes = {@ParamType(type = TypeCheckedTag.class)})
      })
  public boolean isDevDependency(TypeCheckedTag tag) {
    return tag.isDevDependency();
  }

  @StarlarkMethod(
      name = "extension_metadata",
      doc =
          "Constructs an opaque object that can be returned from the module extension's"
              + " implementation function to provide metadata about the repositories generated by"
              + " the extension to Bazel.",
      parameters = {
        @Param(
            name = "root_module_direct_deps",
            doc =
                "The names of the repositories that the extension considers to be direct"
                    + " dependencies of the root module. If the root module imports additional"
                    + " repositories or does not import all of these repositories via <a"
                    + " href=\"../globals/module.html#use_repo\"><code>use_repo</code></a>, Bazel"
                    + " will print a warning and a fixup command when the extension is"
                    + " evaluated.<p>If one of <code>root_module_direct_deps</code> and"
                    + " <code>root_module_direct_dev_deps</code> is specified, the other has to be"
                    + " as well. The lists specified by these two parameters must be"
                    + " disjoint.<p>Exactly one of <code>root_module_direct_deps</code> and"
                    + " <code>root_module_direct_dev_deps</code> can be set to the special value"
                    + " <code>\"all\"</code>, which is treated as if a list with the names of"
                    + " allrepositories generated by the extension was specified as the value.",
            positional = false,
            named = true,
            defaultValue = "None",
            allowedTypes = {
              @ParamType(type = Sequence.class, generic1 = String.class),
              @ParamType(type = String.class),
              @ParamType(type = NoneType.class)
            }),
        @Param(
            name = "root_module_direct_dev_deps",
            doc =
                "The names of the repositories that the extension considers to be direct dev"
                    + " dependencies of the root module. If the root module imports additional"
                    + " repositories or does not import all of these repositories via <a"
                    + " href=\"../globals/module.html#use_repo\"><code>use_repo</code></a> on an"
                    + " extension proxy created with <code><a"
                    + " href=\"../globals/module.html#use_extension>use_extension</a>(...,"
                    + " dev_dependency = True)</code>, Bazel will print a warning and a fixup"
                    + " command when the extension is evaluated.<p>If one of"
                    + " <code>root_module_direct_deps</code> and"
                    + " <code>root_module_direct_dev_deps</code> is specified, the other has to be"
                    + " as well. The lists specified by these two parameters must be"
                    + " disjoint.<p>Exactly one of <code>root_module_direct_deps</code> and"
                    + " <code>root_module_direct_dev_deps</code> can be set to the special value"
                    + " <code>\"all\"</code>, which is treated as if a list with the names of"
                    + " allrepositories generated by the extension was specified as the value.",
            positional = false,
            named = true,
            defaultValue = "None",
            allowedTypes = {
              @ParamType(type = Sequence.class, generic1 = String.class),
              @ParamType(type = String.class),
              @ParamType(type = NoneType.class)
            }),
      })
  public ModuleExtensionMetadata extensionMetadata(
      Object rootModuleDirectDepsUnchecked, Object rootModuleDirectDevDepsUnchecked)
      throws EvalException {
    return ModuleExtensionMetadata.create(
        rootModuleDirectDepsUnchecked, rootModuleDirectDevDepsUnchecked);
  }
}
