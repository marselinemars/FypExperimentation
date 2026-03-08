# -------
# Evaluaiton code for EoH on TSP
#--------
# More results may refer to 
# Liu, Fei, Xialiang Tong, Mingxuan Yuan, and Qingfu Zhang.
# "Algorithm evolution using large language model." 
# arXiv preprint arXiv:2311.15249 (2023).


from evaluation import Evaluation
import os
import pickle
import time

debug_mode = False
# problem_size = [10,20,50,100,200]
problem_size = [20,50,100]
n_test_ins = 64


def get_extra_output_path():
    run_dir = os.environ.get("EOH_RUN_DIR")
    if not run_dir:
        return None
    output_dir = os.path.join(run_dir, "posthoc_eval", "tsp_construct")
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, "results.txt")


print("Start evaluation...")
extra_output_path = get_extra_output_path()
with open("results.txt", "w") as file:
    extra_file = open(extra_output_path, "w") if extra_output_path else None
    for size in problem_size:
        instance_file_name = './testingdata/instance_data_' + str(size)+ '.pkl'
        with open(instance_file_name, 'rb') as f:
            instance_dataset = pickle.load(f)

        eva = Evaluation(size,instance_dataset,n_test_ins,debug_mode)

        time_start = time.time()
        gap = eva.evaluate()

        result = (f"Average dis on {n_test_ins} instance with size {size} is: {gap:7.3f} timecost: {time.time()-time_start:7.3f}")
        print(result)
        file.write(result + "\n")
        if extra_file is not None:
            extra_file.write(result + "\n")

    if extra_file is not None:
        extra_file.close()
        


