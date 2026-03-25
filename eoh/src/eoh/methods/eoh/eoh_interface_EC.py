import numpy as np
import time
import uuid
import hashlib
from .eoh_evolution import Evolution
import warnings
from joblib import Parallel, delayed
from .evaluator_accelerate import add_numba_decorator
import re
import concurrent.futures
from ...utils.seeding import derive_seed, set_global_seeds
from ...behavior import BehaviorPipeline

class InterfaceEC():
    def __init__(self, pop_size, m, api_endpoint, api_key, llm_model,llm_use_local,llm_local_url, debug_mode, interface_prob, select,n_p,timeout,use_numba, logger=None, worker_seed_base=None, behavior_enabled=False, behavior_config_path=None, behavior_system_id=None, **kwargs):

        # LLM settings
        self.pop_size = pop_size
        self.interface_eval = interface_prob
        prompts = interface_prob.prompts
        self.evol = Evolution(api_endpoint, api_key, llm_model,llm_use_local,llm_local_url, debug_mode,prompts, **kwargs)
        self.m = m
        self.debug = debug_mode

        if not self.debug:
            warnings.filterwarnings("ignore")

        self.select = select
        self.n_p = n_p
        
        self.timeout = timeout
        self.use_numba = use_numba
        self.logger = logger
        self.worker_seed_base = worker_seed_base
        self.behavior_pipeline = None
        if behavior_enabled and logger is not None and interface_prob.__class__.__name__ in ["BPONLINE", "TSPCONST"]:
            self.behavior_pipeline = BehaviorPipeline(
                interface_prob,
                logger,
                config_path=behavior_config_path,
                system_id=behavior_system_id or "S4a",
            )

    def _text_hash(self, value):
        if value is None:
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _get_evaluation_error(self):
        evaluation_error = getattr(self.interface_eval, "last_evaluation_error", None)
        if isinstance(evaluation_error, dict):
            return {
                "type": evaluation_error.get("type"),
                "message": evaluation_error.get("message"),
            }
        return None

    def _summarize_parent(self, parent):
        if parent is None:
            return None
        return {
            "objective": parent.get("objective"),
            "code_sha256": self._text_hash(parent.get("code")),
            "algorithm_sha256": self._text_hash(parent.get("algorithm")),
            "algorithm_preview": (parent.get("algorithm") or "")[:200],
        }
        
    def code2file(self,code):
        with open("./ael_alg.py", "w") as file:
        # Write the code to the file
            file.write(code)
        return 
    
    def add2pop(self,population,offspring):
        for ind in population:
            if ind['objective'] == offspring['objective']:
                if self.debug:
                    print("duplicated result, retrying ... ")
                return False
        population.append(offspring)
        return True
    
    def check_duplicate(self,population,code):
        for ind in population:
            if code == ind['code']:
                return True
        return False

    # def population_management(self,pop):
    #     # Delete the worst individual
    #     pop_new = heapq.nsmallest(self.pop_size, pop, key=lambda x: x['objective'])
    #     return pop_new
    
    # def parent_selection(self,pop,m):
    #     ranks = [i for i in range(len(pop))]
    #     probs = [1 / (rank + 1 + len(pop)) for rank in ranks]
    #     parents = random.choices(pop, weights=probs, k=m)
    #     return parents

    def population_generation(self):
        
        n_create = 2
        
        population = []

        for i in range(n_create):
            _,pop = self.get_algorithm([], 'i1', context={"population_index": 0, "operator_index": 0, "operator_count": 1, "initialization_batch": i + 1})
            for p in pop:
                population.append(p)
             
        return population
    
    def population_generation_seed(self,seeds,n_p):

        population = []

        fitness = Parallel(n_jobs=n_p)(delayed(self.interface_eval.evaluate)(seed['code']) for seed in seeds)

        for i in range(len(seeds)):
            try:
                seed_alg = {
                    'algorithm': seeds[i]['algorithm'],
                    'code': seeds[i]['code'],
                    'objective': None,
                    'other_inf': None
                }

                obj = np.array(fitness[i])
                seed_alg['objective'] = np.round(obj, 5)
                population.append(seed_alg)

            except Exception as e:
                print("Error in seed algorithm")
                exit()

        print("Initiliazation finished! Get "+str(len(seeds))+" seed algorithms")

        return population
    

    def _get_alg(self,pop,operator):
        offspring = {
            'algorithm': None,
            'code': None,
            'objective': None,
            'other_inf': None
        }
        llm_trace = None
        if operator == "i1":
            parents = None
            [offspring['code'],offspring['algorithm'], llm_trace] =  self.evol.i1()
        elif operator == "e1":
            parents = self.select.parent_selection(pop,self.m)
            [offspring['code'],offspring['algorithm'], llm_trace] = self.evol.e1(parents)
        elif operator == "e2":
            parents = self.select.parent_selection(pop,self.m)
            [offspring['code'],offspring['algorithm'], llm_trace] = self.evol.e2(parents)
        elif operator == "m1":
            parents = self.select.parent_selection(pop,1)
            [offspring['code'],offspring['algorithm'], llm_trace] = self.evol.m1(parents[0])
        elif operator == "m2":
            parents = self.select.parent_selection(pop,1)
            [offspring['code'],offspring['algorithm'], llm_trace] = self.evol.m2(parents[0])
        elif operator == "m3":
            parents = self.select.parent_selection(pop,1)
            [offspring['code'],offspring['algorithm'], llm_trace] = self.evol.m3(parents[0])
        else:
            print(f"Evolution operator [{operator}] has not been implemented ! \n") 

        return parents, offspring, llm_trace

    def get_offspring(self, pop, operator, context=None):
        context = context or {}
        attempt_id = uuid.uuid4().hex
        started_at = time.time()
        task_index = context.get("task_index", 0)
        attempt_seed = derive_seed(
            self.worker_seed_base,
            operator,
            context.get("population_index"),
            context.get("operator_index"),
            context.get("initialization_batch"),
            task_index,
            "attempt",
        )
        evaluation_seed = derive_seed(
            self.worker_seed_base,
            operator,
            context.get("population_index"),
            context.get("operator_index"),
            context.get("initialization_batch"),
            task_index,
            "evaluation",
        )
        log_record = {
            "attempt_id": attempt_id,
            "operator": operator,
            "population_index": context.get("population_index"),
            "operator_index": context.get("operator_index"),
            "operator_count": context.get("operator_count"),
            "initialization_batch": context.get("initialization_batch"),
            "task_index": task_index,
            "pop_size": self.pop_size,
            "parent_count_requested": self.m if operator in ["e1", "e2"] else (0 if operator == "i1" else 1),
            "timeout_seconds": self.timeout,
            "used_numba": self.use_numba,
            "worker_seed_attempt": attempt_seed,
            "worker_seed_evaluation": evaluation_seed,
            "status": "invalid",
            "error_type": None,
            "error_message": None,
            "objective": None,
            "code_sha256": None,
            "algorithm_sha256": None,
            "raw_code_sha256": None,
            "evaluation_code_sha256": None,
            "parents": [],
            "llm_trace": None,
            "elapsed_seconds": None,
        }

        try:
            set_global_seeds(attempt_seed, attempt_seed)
            p, offspring, llm_trace = self._get_alg(pop, operator)
            parent_list = p if isinstance(p, list) else ([p] if p is not None else [])
            log_record["parents"] = [self._summarize_parent(parent) for parent in parent_list]
            log_record["llm_trace"] = llm_trace
            log_record["raw_code_sha256"] = self._text_hash(offspring["code"])
            log_record["algorithm_sha256"] = self._text_hash(offspring["algorithm"])
            
            if self.use_numba:
                
                # Regular expression pattern to match function definitions
                pattern = r"def\s+(\w+)\s*\(.*\):"

                # Search for function definitions in the code
                match = re.search(pattern, offspring['code'])

                function_name = match.group(1)

                code = add_numba_decorator(program=offspring['code'], function_name=function_name)
            else:
                code = offspring['code']
            log_record["evaluation_code_sha256"] = self._text_hash(code)

            n_retry= 1
            while self.check_duplicate(pop, offspring['code']):
                
                n_retry += 1
                if self.debug:
                    print("duplicated code, wait 1 second and retrying ... ")
                    
                p, offspring, llm_trace = self._get_alg(pop, operator)
                parent_list = p if isinstance(p, list) else ([p] if p is not None else [])
                log_record["parents"] = [self._summarize_parent(parent) for parent in parent_list]
                log_record["llm_trace"] = llm_trace
                log_record["raw_code_sha256"] = self._text_hash(offspring["code"])
                log_record["algorithm_sha256"] = self._text_hash(offspring["algorithm"])

                if self.use_numba:
                    # Regular expression pattern to match function definitions
                    pattern = r"def\s+(\w+)\s*\(.*\):"

                    # Search for function definitions in the code
                    match = re.search(pattern, offspring['code'])

                    function_name = match.group(1)

                    code = add_numba_decorator(program=offspring['code'], function_name=function_name)
                else:
                    code = offspring['code']
                log_record["evaluation_code_sha256"] = self._text_hash(code)
                    
                if n_retry > 1:
                    break
                
                
            #self.code2file(offspring['code'])
            set_global_seeds(evaluation_seed, evaluation_seed)
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(self.interface_eval.evaluate, code)
                fitness = future.result(timeout=self.timeout)
                if fitness is None:
                    evaluation_error = self._get_evaluation_error()
                    if evaluation_error is not None:
                        log_record["error_type"] = evaluation_error.get("type")
                        log_record["error_message"] = evaluation_error.get("message")
                    else:
                        log_record["error_type"] = "ValueError"
                        log_record["error_message"] = "candidate evaluation returned None"
                    raise ValueError("candidate evaluation returned None")
                offspring['objective'] = np.round(fitness, 5)
                future.cancel()        
                # fitness = self.interface_eval.evaluate(code)
            log_record["status"] = "valid"
            log_record["objective"] = offspring["objective"]
            log_record["code_sha256"] = self._text_hash(offspring["code"])


        except Exception as e:
            if log_record["error_type"] is None:
                log_record["error_type"] = type(e).__name__
            if log_record["error_message"] is None:
                log_record["error_message"] = str(e)

            offspring = {
                'algorithm': None,
                'code': None,
                'objective': None,
                'other_inf': None
            }
            p = None

        log_record["elapsed_seconds"] = round(time.time() - started_at, 6)
        # Round the objective values
        return p, offspring, log_record
    # def process_task(self,pop, operator):
    #     result =  None, {
    #             'algorithm': None,
    #             'code': None,
    #             'objective': None,
    #             'other_inf': None
    #         }
    #     with concurrent.futures.ThreadPoolExecutor() as executor:
    #         future = executor.submit(self.get_offspring, pop, operator)
    #         try:
    #             result = future.result(timeout=self.timeout)
    #             future.cancel()
    #             #print(result)
    #         except:
    #             future.cancel()
                
    #     return result

    
    def get_algorithm(self, pop, operator, context=None):
        results = []
        try:
            results = Parallel(n_jobs=self.n_p,timeout=self.timeout+15)(
                delayed(self.get_offspring)(
                    pop,
                    operator,
                    context={**(context or {}), "task_index": task_index},
                )
                for task_index in range(self.pop_size)
            )
        except Exception as e:
            if self.debug:
                print(f"Error: {e}")
            print("Parallel time out .")
            
        time.sleep(2)


        out_p = []
        out_off = []

        for p, off, log_record in results:
            out_p.append(p)
            out_off.append(off)
            if self.logger is not None:
                persisted_record = self.logger.log_candidate_attempt(log_record)
                if self.behavior_pipeline is not None:
                    self.behavior_pipeline.analyze_and_log_candidate(persisted_record, off)
            if self.debug:
                print(f">>> check offsprings: \n {off}")
        return out_p, out_off
    # def get_algorithm(self,pop,operator, pop_size, n_p):
        
    #     # perform it pop_size times with n_p processes in parallel
    #     p,offspring = self._get_alg(pop,operator)
    #     while self.check_duplicate(pop,offspring['code']):
    #         if self.debug:
    #             print("duplicated code, wait 1 second and retrying ... ")
    #         time.sleep(1)
    #         p,offspring = self._get_alg(pop,operator)
    #     self.code2file(offspring['code'])
    #     try:
    #         fitness= self.interface_eval.evaluate()
    #     except:
    #         fitness = None
    #     offspring['objective'] =  fitness
    #     #offspring['other_inf'] =  first_gap
    #     while (fitness == None):
    #         if self.debug:
    #             print("warning! error code, retrying ... ")
    #         p,offspring = self._get_alg(pop,operator)
    #         while self.check_duplicate(pop,offspring['code']):
    #             if self.debug:
    #                 print("duplicated code, wait 1 second and retrying ... ")
    #             time.sleep(1)
    #             p,offspring = self._get_alg(pop,operator)
    #         self.code2file(offspring['code'])
    #         try:
    #             fitness= self.interface_eval.evaluate()
    #         except:
    #             fitness = None
    #         offspring['objective'] =  fitness
    #         #offspring['other_inf'] =  first_gap
    #     offspring['objective'] = np.round(offspring['objective'],5) 
    #     #offspring['other_inf'] = np.round(offspring['other_inf'],3)
    #     return p,offspring
