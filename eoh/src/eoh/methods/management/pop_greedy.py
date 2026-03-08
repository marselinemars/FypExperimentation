import heapq

def population_management(pop,size):
    pop = [individual for individual in pop if individual['objective'] is not None]
    if size > len(pop):
        size = len(pop)
    pop_new = heapq.nsmallest(size, pop, key=lambda x: x['objective'])
    return pop_new
