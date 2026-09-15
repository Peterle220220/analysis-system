"""Turning what a person chose into a plan that analyses it.

This is the half of the feature work that reaches back into an existing run. A
selection is not a new question - it is the same question asked about less of the
data - so it does not produce a new plan. It rewrites the parameters of the tasks
that consume features and leaves everything else alone.

What happens next is not this module's doing, and that is the point. Because task
parameters are part of a task's identity (L40), a changed selection invalidates
exactly the tasks whose instructions changed, their outputs change, and the tasks
downstream of *those* re-run because their inputs changed. Nothing here has to
know which tasks depend on which. Had that fix not gone in first, this would have
returned the previous answer to the new question without a word - which is why it
went in first.
"""

from __future__ import annotations

from pathlib import Path

from analysis_system.core.boundary import Manifest, load_manifest
from analysis_system.models.agents import Plan, PlannedTask
from analysis_system.services.features import (
    FeatureCatalogue,
    FeatureError,
    Selection,
    parse_key,
)


def _params_from(
    manifest: Manifest, selection: Selection, catalogue: FeatureCatalogue
) -> dict[str, list[str]]:
    """The parameters this agent should be given, for this selection.

    A parameter that would come out empty is still written, as an empty list.
    Leaving it out would let the task fall back to whatever it did before, and
    the fallback for "which columns to measure" is *all of them* - so narrowing a
    selection would silently widen the analysis.
    """
    built: dict[str, list[str]] = {}
    for binding in manifest.consumes_features:
        names: list[str] = []
        for key in selection.keys:
            kind, name = parse_key(key)
            if kind != binding.kind:
                continue
            feature = catalogue.get(key)
            if feature is not None and binding.accepts(feature.role):
                names.append(name)
        built[binding.param] = sorted(names)
    return built


def apply_selection(
    plan: Plan,
    selection: Selection,
    catalogue: FeatureCatalogue,
    manifest_dir: Path | None = None,
) -> Plan:
    """The same plan, told to analyse only what was chosen.

    Args:
        plan: the plan to rewrite. It is not modified.
        selection: what the person chose. Empty means everything, and the plan
            comes back untouched.
        catalogue: what was choosable, used to look up each feature's role.
        manifest_dir: where the manifests live.

    Returns:
        A plan whose feature-consuming tasks carry the chosen features.

    Raises:
        FeatureError: the selection names something the data does not have, or
            it names nothing that any task in this plan can use.
    """
    if selection.is_empty:
        return plan
    selection.validate(catalogue)

    tasks: list[PlannedTask] = []
    touched = 0
    for task in plan.tasks:
        manifest = load_manifest(task.agent_id, manifest_dir)
        if not manifest.consumes_features:
            tasks.append(task)
            continue
        params = _params_from(manifest, selection, catalogue)
        if all(not names for names in params.values()):
            # This task consumes features but none of the chosen ones. Leave it
            # exactly as it was rather than blanking its parameters: a selection
            # about activities says nothing about which columns to measure.
            tasks.append(task)
            continue
        touched += 1
        tasks.append(task.model_copy(update={"params": {**task.params, **params}}))

    if not touched:
        raise FeatureError(
            "khong task nao trong ke hoach dung den cac dac trung da chon. "
            "Lua chon nay se khong doi gi ca - kiem lai loai dac trung."
        )
    return plan.model_copy(update={"tasks": tuple(tasks)})


def affected_tasks(
    plan: Plan,
    selection: Selection,
    catalogue: FeatureCatalogue,
    manifest_dir: Path | None = None,
) -> tuple[str, ...]:
    """Which tasks a selection would change, for telling a person before they commit.

    Only the tasks whose parameters change are named. The ones downstream will
    re-run too, because their inputs will differ - but saying so here would be
    guessing at what has not been computed yet.
    """
    if selection.is_empty:
        return ()
    changed = apply_selection(plan, selection, catalogue, manifest_dir)
    before = {task.task_id: task.params for task in plan.tasks}
    return tuple(task.task_id for task in changed.tasks if before.get(task.task_id) != task.params)
