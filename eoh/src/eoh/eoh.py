
import random

from .utils import createFolders
from .utils.runLogger import RunLogger
from .utils.seeding import set_global_seeds
from .methods import methods
from .problems import problems

# main class for AEL
class EVOL:

    # initilization
    def __init__(self, paras, prob=None, **kwargs):

        print("----------------------------------------- ")
        print("---              Start EoH            ---")
        print("-----------------------------------------")
        # Create a unique run directory and place all artifacts inside it.
        self.logger = RunLogger(paras.exp_output_path)
        paras.exp_base_output_path = self.logger.base_output_path
        paras.exp_run_id = self.logger.run_id
        paras.exp_run_dir = self.logger.run_dir
        paras.exp_logger = self.logger
        paras.exp_output_path = self.logger.run_dir
        # Create folder #
        createFolders.create_folders(paras.exp_output_path)
        print("- output folder created -")

        self.paras = paras

        print("-  parameters loaded -")

        self.prob = prob

        # Set reproducible main-process seeds before problem and method setup.
        set_global_seeds(paras.exp_python_seed, paras.exp_numpy_seed)

        
    # run methods
    def run(self):

        problemGenerator = problems.Probs(self.paras)

        problem = problemGenerator.get_problem()

        methodGenerator = methods.Methods(self.paras,problem)

        method = methodGenerator.get_method()

        manifest = self.logger.build_manifest(
            self.paras,
            extra={
                "problem_class": problem.__class__.__name__ if problem is not None else None,
                "method_class": method.__class__.__name__ if method is not None else None,
            },
        )
        self.logger.write_manifest(manifest)

        summary = {
            "problem_class": problem.__class__.__name__ if problem is not None else None,
            "method_class": method.__class__.__name__ if method is not None else None,
            "results_dir": self.paras.exp_output_path,
            "run_status": "completed",
            "error_type": None,
            "error_message": None,
        }

        try:
            method.run()
        except Exception as exc:
            summary["run_status"] = "failed"
            summary["error_type"] = type(exc).__name__
            summary["error_message"] = str(exc)
            if hasattr(method, "get_run_summary"):
                summary.update(method.get_run_summary())
            self.logger.write_summary(summary)
            raise

        if hasattr(method, "get_run_summary"):
            summary.update(method.get_run_summary())
        self.logger.write_summary(summary)

        print("> End of Evolution! ")
        print("----------------------------------------- ")
        print("---     EoH successfully finished !   ---")
        print("-----------------------------------------")
