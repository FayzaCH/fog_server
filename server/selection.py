'''
    Host and path selection algorithms for network applications based on their 
    requirements. It uses the Strategy design pattern to make it easier to 
    define various algorithms that can be chosen at runtime.

    Classes:
    --------
    NodeSelector: Node selector through given algorithm.

    PathSelector: Path selector through given algorithm. 

    Algorithms:
    -----------
    SIMPLENODE: Simple selection of nodes that satisfy required CPU, RAM, 
    and disk.

    DIJKSTRA: Best path selection based on Dijkstra's shortest path algorithm. 
    Calculates link weights and gets the shortest path from the source node to 
    each potential destination node.

    LEASTCOST: Best path selection based on path cost that is calculated with 
    an equation that includes bandwidth cost, delay cost, jitter cost, and 
    loss rate cost.
'''


from networkx import DiGraph, single_source_dijkstra, all_simple_paths

from model import Node, Request


# host selection algorithms
SIMPLE_NODE = 'SIMPLE'

# path selection algorithms
DIJKSTRA_PATH = 'DIJKSTRA'
LEASTCOST_PATH = 'LEASTCOST'

# path weights
HOP_WEIGHT = 'HOP'
DELAY_WEIGHT = 'DELAY'
COST_WEIGHT = 'COST'

# selection strategies
ALL = 'ALL'
FIRST = 'FIRST'
BEST = 'BEST'

NODE_ALGORITHMS = [None, '', SIMPLE_NODE]
PATH_ALGORITHMS = [None, '', DIJKSTRA_PATH, LEASTCOST_PATH]
WEIGHTS = [None, '', HOP_WEIGHT, DELAY_WEIGHT, COST_WEIGHT]
STRATEGIES = [None, '', ALL, FIRST, BEST]


class NodeSelector:
    '''
        Node selector through given algorithm.

        Algorithms:
        -----------
        SIMPLENODE: Simple selection of nodes that satisfy required CPU, RAM, 
        and disk.

        Methods:
        --------
        select(nodes, req, strategy): Select node(s) that satisfy req through 
        given algorithm and based on given strategy (ALL or FIRST). Default 
        strategy is ALL.
    '''

    def __init__(self, algorithm: str = ''):
        if not algorithm or algorithm.upper() == SIMPLE_NODE:
            self._algorithm = _SimpleNodeSelection()
        else:
            raise Exception('Requested algorithm does not exist')

    def select(self, nodes: list, req: Request, strategy: str = ALL):
        '''
            Select node(s) that satisfy req through given algorithm and based 
            on given strategy (ALL or FIRST). Default strategy is ALL.

            Returns selected Node(s).
        '''
        return self._algorithm.select(nodes, req, strategy)


class PathSelector:
    '''
        Path selector through given algorithm. 

        Algorithms:
        -----------
        DIJKSTRA: Best path selection based on Dijkstra's shortest path 
        algorithm. Calculates link weights and gets the shortest path from the 
        source node to each potential destination node.

        LEASTCOST: Best path selection based on path cost that is calculated 
        with an equation that includes bandwidth cost, delay cost, jitter cost, 
        and loss rate cost.

        Methods:
        --------
        select(graph, dst, req, weight, strategy): Select path(s) in graph 
        from req.src to target Nodes, that satisfy req through given algorithm 
        and based on given weight (HOP, DELAY, COST, etc.) and given strategy 
        (ALL or BEST). Default weight is nothing (all edges are equal). 
        Default strategy is ALL.
    '''

    def __init__(self, algorithm: str = ''):
        if not algorithm or algorithm.upper() == DIJKSTRA_PATH:
            self._algorithm = _DijkstraPathSelection()
        elif algorithm.upper() == LEASTCOST_PATH:
            self._algorithm = _LeastCostPathSelection()
        else:
            raise Exception('Requested algorithm does not exist')

    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ALL):
        '''
            Select path(s) in graph from req.src to target Nodes, that satisfy 
            req through given algorithm and based on given weight (HOP, DELAY, 
            COST, etc.) and given strategy (ALL or BEST). Default weight is 
            nothing (all edges are equal). Default strategy is ALL.

            Returns selected path(s) and weight(s).
        '''
        return self._algorithm.select(graph, targets, req, weight, strategy)


# =================================
#     Node Selection Algorithms
# =================================


class _NodeSelection:
    def select(self, nodes: list, req: Request, strategy: str = ALL):
        pass


class _SimpleNodeSelection(_NodeSelection):
    def select(self, nodes: list, req: Request, strategy: str = ALL):
        def _check_resources(node: Node, req: Request):
            return (node != req.src  # exclude source node
                    and node.state == True
                    and node.get_cpu() >= req.get_min_cpu()
                    and node.get_ram() >= req.get_min_ram()
                    and node.get_disk() >= req.get_min_disk())

        if strategy == ALL:
            return [node for node in nodes if _check_resources(node, req)]
        if strategy == FIRST:
            for node in nodes:
                if _check_resources(node, req):
                    return node


# =================================
#     Path Selection Algorithms
# =================================


class _PathSelection:
    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ALL):
        pass


class _DijkstraPathSelection(_PathSelection):
    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ALL):
        if weight == DELAY_WEIGHT:
            def weight_func(u, v, d):
                return d['link'].get_delay()
        else:
            weight_func = 1

        # TODO calculate cutoff from requirements

        lengths, paths = single_source_dijkstra(graph, req.src.id, cutoff=None,
                                                weight=weight_func)

        targs = [target.id for target in targets]

        if strategy == ALL:
            return ({target: [paths[target]]
                     for target in paths if target in targs},
                    {target: [lengths[target]]
                     for target in lengths if target in targs})

        if strategy == BEST:
            best_length = float('inf')
            best_path = None
            for target in lengths:
                if target in targs and lengths[target] < best_length:
                    best_length = lengths[target]
                    best_path = paths[target]
            return best_path, best_length


class _LeastCostPathSelection(_PathSelection):
    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ALL):
        def calc_cost(path):
            len_path = len(path)
            Ct = float('inf')
            BWp = float('inf')
            Bw = 0
            Dp = 0
            Jp = 0
            LRp = 1
            for i in range(1, len_path):
                Pi = graph[path[i-1]][path[i]]['link']
                cap = Pi.get_capacity()
                Ct = min(Ct, cap)
                free_bw = Pi.get_bandwidth()
                BWp = min(BWp, free_bw)
                Bw += (cap - free_bw)
                Dp += Pi.get_delay()
                Jp += Pi.get_jitter()
                LRp *= (1 - Pi.get_loss_rate())
            LRp = 1 - LRp

            CDp = req.get_max_delay() / Dp
            CJp = req.get_max_jitter() / Jp
            CLRp = req.get_max_loss_rate() / LRp
            BWc = req.get_min_bandwidth()
            CBWp = BWc / (Ct - (Bw + BWc))
            return CBWp / (CDp * CJp * CLRp)

        targs = [target.id for target in targets]
        paths = all_simple_paths(graph, req.src.id, targs)

        if strategy == ALL:
            weights = {}
            paths_dict = {}
        if strategy == BEST:
            min_Cpath = float('inf')
            min_path = None

        for path in paths:
            try:
                Cpath = calc_cost(path)
            except:
                Cpath = float('inf')

            if strategy == ALL:
                dst = path[-1]
                weights.setdefault(dst, [])
                weights[dst].append(Cpath)
                paths_dict.setdefault(dst, [])
                paths_dict[dst].append(path)
            if strategy == BEST:
                if Cpath < min_Cpath:
                    min_Cpath = Cpath
                    min_path = path

        if strategy == ALL:
            return paths_dict, weights
        if strategy == BEST:
            return min_path, min_Cpath
