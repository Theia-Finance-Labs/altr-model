"""Project hooks."""
from kedro.framework.hooks import hook_impl

from crispy_kedro.pipelines.inputs_processing.nodes import validate_parameters


class ParameterValidationHooks:
    """Fail fast on a bad parameter before any node runs, under any runner.

    A validation node with no data dependencies is only topologically first by
    accident, so the check lives here instead.
    """

    @hook_impl
    def before_pipeline_run(self, run_params, pipeline, catalog) -> None:
        validate_parameters(catalog.load("parameters"))
