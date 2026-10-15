"""Слот cost/loop-guards. Реализуются вместе со срезом token-инструментирования.

Планируемые guards (НЕ реализованы — фейк-CONTINUE запрещён):
  MaxLLMCallsPerStage, MaxBrowserRetriesPerStage, NoRepeatedDOMDumpIfSnapshotExists,
  UseCachedATSMappingIfAvailable, UseStructuredVacancyIfAvailable,
  StopBroadAgentLoopAfterFailure.
"""
