"""Custom hooks for crispy-kedro package."""

import logging
from typing import Any, Dict

from kedro.framework.hooks import hook_impl
from kedro.framework.session.session import KedroSession

logger = logging.getLogger(__name__)


class MlflowCleanupHook:
    """Hook to manage MLflow run cleanup in Celery environment."""

    @hook_impl
    def before_pipeline_run(
        self, run_params: Dict[str, Any], pipeline: Any, catalog: Any
    ) -> None:
        """Clean up any lingering MLflow runs before starting a new pipeline."""
        try:
            # Only perform cleanup if MLflow is enabled
            import os

            if os.getenv("ENABLE_MLFLOW", "false").lower() != "true":
                return

            import mlflow

            # Aggressively clean up any lingering MLflow runs from previous executions
            cleanup_count = 0
            max_cleanup = 3  # Safety limit

            while mlflow.active_run() and cleanup_count < max_cleanup:
                active_run = mlflow.active_run()
                run_id = active_run.info.run_id
                logger.warning(
                    f"Found lingering MLflow run {run_id} from previous execution, ending it"
                )
                mlflow.end_run()
                cleanup_count += 1

            if cleanup_count > 0:
                logger.info(
                    f"Cleaned up {cleanup_count} lingering MLflow run(s) before starting new pipeline"
                )
            else:
                logger.debug("No lingering MLflow runs found")

        except Exception as e:
            logger.warning(f"Error during MLflow state check: {e}")
            # Don't fail the pipeline if cleanup fails
            pass

    @hook_impl
    def after_pipeline_run(
        self, run_params: Dict[str, Any], pipeline: Any, catalog: Any
    ) -> None:
        """Ensure MLflow run is properly closed after pipeline execution."""
        try:
            import os

            if os.getenv("ENABLE_MLFLOW", "false").lower() != "true":
                return

            import mlflow

            # Ensure the current run is properly ended
            if mlflow.active_run():
                run_id = mlflow.active_run().info.run_id
                logger.info(f"Ending MLflow run {run_id} after pipeline completion")
                mlflow.end_run()

        except Exception as e:
            logger.warning(f"Error during MLflow run cleanup: {e}")
            # Don't fail the pipeline if cleanup fails
            pass
