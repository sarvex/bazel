// Copyright 2022 The Bazel Authors. All rights reserved.
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
package com.google.devtools.build.lib.runtime;

import static com.google.common.base.Preconditions.checkState;
import static com.google.devtools.build.lib.concurrent.NamedForkJoinPool.newNamedPool;

import com.google.common.annotations.VisibleForTesting;
import com.google.devtools.build.lib.analysis.AnalysisOptions;
import com.google.devtools.build.lib.buildtool.BuildRequestOptions;
import com.google.devtools.build.lib.concurrent.AbstractQueueVisitor;
import com.google.devtools.build.lib.concurrent.AbstractQueueVisitor.ExceptionHandlingMode;
import com.google.devtools.build.lib.concurrent.MultiExecutorQueueVisitor;
import com.google.devtools.build.lib.concurrent.QuiescingExecutor;
import com.google.devtools.build.lib.concurrent.QuiescingExecutors;
import com.google.devtools.build.lib.concurrent.TieredPriorityExecutor;
import com.google.devtools.build.lib.pkgcache.PackageOptions;
import com.google.devtools.build.skyframe.ParallelEvaluatorErrorClassifier;
import com.google.devtools.common.options.OptionsProvider;

/**
 * Encapsulates thread pool options used by parallel evaluation.
 *
 * <p>This object has a server-scoped lifetime, but has its parameters refreshed by a call to {@link
 * #resetParameters} per-command.
 */
public final class QuiescingExecutorsImpl implements QuiescingExecutors {
  private static final String SKYFRAME_EVALUATOR = "skyframe-evaluator";
  private static final String SKYFRAME_EVALUATOR_CPU_HEAVY = "skyframe-evaluator-cpu-heavy";
  private static final String SKYFRAME_EVALUATOR_EXECUTION = "skyframe-evaluator-execution";

  private int analysisParallelism;
  private int executionParallelism;
  private int globbingParallelism;

  /**
   * The size of the thread pool for CPU-heavy tasks set by
   * -experimental_skyframe_cpu_heavy_skykeys_thread_pool_size.
   *
   * <p>--experimental_skyframe_cpu_heavy_skykeys_thread_pool_size is not used in the execution
   * phase.
   */
  private int cpuHeavySkyKeysThreadPoolSize;

  private boolean usePrioritizationForAnalysis;

  @VisibleForTesting
  public static QuiescingExecutors forTesting() {
    return new QuiescingExecutorsImpl(
        /* analysisParallelism= */ 6,
        /* executionParallelism= */ 6,
        /* globbingParallelism= */ 6,
        /* cpuHeavySkyKeysThreadPoolSize= */ 4,
        // Prioritization needs more test coverage.
        /* usePrioritizationForAnalysis= */ true);
  }

  static QuiescingExecutorsImpl createDefault() {
    return new QuiescingExecutorsImpl(
        /* analysisParallelism= */ 0,
        /* executionParallelism= */ 0,
        /* globbingParallelism= */ 0,
        /* cpuHeavySkyKeysThreadPoolSize= */ 0,
        /* usePrioritizationForAnalysis= */ false);
  }

  private QuiescingExecutorsImpl(
      int analysisParallelism,
      int executionParallelism,
      int globbingParallelism,
      int cpuHeavySkyKeysThreadPoolSize,
      boolean usePrioritizationForAnalysis) {
    this.analysisParallelism = analysisParallelism;
    this.executionParallelism = executionParallelism;
    this.globbingParallelism = globbingParallelism;
    this.cpuHeavySkyKeysThreadPoolSize = cpuHeavySkyKeysThreadPoolSize;
    this.usePrioritizationForAnalysis = usePrioritizationForAnalysis;
  }

  void resetParameters(OptionsProvider options) {
    // When options are missing, it is because the current command does not provide those options.
    // In that case, the values are undefined and callers should not be accessing the associated
    // executors. Having the values set to 0 causes check failures with the intention to catch such
    // errors early in tests or canary processes.
    //
    // TODO(shahan): consider whether it is better to have robust defaults instead, at the cost of
    // possibly allowing bugs here to go unnoticed.
    var loadingPhaseThreadsOption = options.getOptions(LoadingPhaseThreadsOption.class);
    this.analysisParallelism =
        loadingPhaseThreadsOption != null ? loadingPhaseThreadsOption.threads : 0;
    var buildRequestOptions = options.getOptions(BuildRequestOptions.class);
    this.executionParallelism = buildRequestOptions != null ? buildRequestOptions.jobs : 0;
    var packageOptions = options.getOptions(PackageOptions.class);
    this.globbingParallelism = packageOptions != null ? packageOptions.globbingThreads : 0;
    var analysisOptions = options.getOptions(AnalysisOptions.class);
    this.cpuHeavySkyKeysThreadPoolSize =
        analysisOptions != null ? analysisOptions.cpuHeavySkyKeysThreadPoolSize : 0;
    if (analysisOptions != null) {
      this.cpuHeavySkyKeysThreadPoolSize = analysisOptions.cpuHeavySkyKeysThreadPoolSize;
      if ((this.usePrioritizationForAnalysis = analysisOptions.usePrioritization)) {
        if (cpuHeavySkyKeysThreadPoolSize > analysisParallelism) {
          // The prioritizing executor requires the CPU heavy pool size to be no more than
          // analysis parallelism.
          this.cpuHeavySkyKeysThreadPoolSize = analysisParallelism;
        }
      }
    } else {
      this.cpuHeavySkyKeysThreadPoolSize = 0;
      this.usePrioritizationForAnalysis = false;
    }
  }

  @Override
  public int analysisParallelism() {
    return analysisParallelism;
  }

  @Override
  public int executionParallelism() {
    return executionParallelism;
  }

  @Override
  public int globbingParallelism() {
    return globbingParallelism;
  }

  @Override
  public boolean usePrioritizationForAnalysis() {
    return usePrioritizationForAnalysis;
  }

  @Override
  public QuiescingExecutor getAnalysisExecutor() {
    checkState(analysisParallelism > 0, "expected analysisParallelism > 0 : %s", this);
    if (cpuHeavySkyKeysThreadPoolSize > 0) {
      if (usePrioritizationForAnalysis) {
        return new TieredPriorityExecutor(
            "skyframe-evaluator",
            analysisParallelism,
            cpuHeavySkyKeysThreadPoolSize,
            ParallelEvaluatorErrorClassifier.instance());
      }
      return MultiExecutorQueueVisitor.createWithExecutorServices(
          newNamedPool(SKYFRAME_EVALUATOR, analysisParallelism),
          AbstractQueueVisitor.createExecutorService(
              /* parallelism= */ cpuHeavySkyKeysThreadPoolSize, SKYFRAME_EVALUATOR_CPU_HEAVY),
          ExceptionHandlingMode.FAIL_FAST,
          ParallelEvaluatorErrorClassifier.instance());
    }
    return AbstractQueueVisitor.create(
        SKYFRAME_EVALUATOR, analysisParallelism(), ParallelEvaluatorErrorClassifier.instance());
  }

  @Override
  public QuiescingExecutor getExecutionExecutor() {
    checkState(executionParallelism > 0, "expected executionParallelism > 0 : %s", this);
    return AbstractQueueVisitor.createWithExecutorService(
        newNamedPool(SKYFRAME_EVALUATOR, executionParallelism),
        ExceptionHandlingMode.FAIL_FAST,
        ParallelEvaluatorErrorClassifier.instance());
  }

  @Override
  public QuiescingExecutor getMergedAnalysisAndExecutionExecutor() {
    checkState(analysisParallelism > 0, "expected analysisParallelism > 0 : %s", this);
    checkState(executionParallelism > 0, "expected executionParallelism > 0 : %s", this);
    checkState(
        cpuHeavySkyKeysThreadPoolSize > 0, "expected cpuHeavySkyKeysThreadPoolSize > 0 : %s", this);
    return MultiExecutorQueueVisitor.createWithExecutorServices(
        newNamedPool(SKYFRAME_EVALUATOR, analysisParallelism),
        AbstractQueueVisitor.createExecutorService(
            /* parallelism= */ cpuHeavySkyKeysThreadPoolSize, SKYFRAME_EVALUATOR_CPU_HEAVY),
        AbstractQueueVisitor.createExecutorService(
            /* parallelism= */ executionParallelism, SKYFRAME_EVALUATOR_EXECUTION),
        ExceptionHandlingMode.FAIL_FAST,
        ParallelEvaluatorErrorClassifier.instance());
  }
}
