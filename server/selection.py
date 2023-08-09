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
    SIMPLE: Simple selection of nodes that satisfy required CPU, RAM, and disk.

    DIJKSTRA: Best path selection based on Dijkstra's shortest path algorithm.
    Calculates link weights and gets the shortest path from the source node to
    each potential destination node.

    LEASTCOST: Best path selection based on path cost that is calculated with
    an equation that includes bandwidth cost, delay cost, jitter cost, and
    loss rate cost.
'''


from networkx import DiGraph, single_source_dijkstra, all_simple_paths

from model import Node, Request
from logger import console, file


# =================================
#     Node Selection Algorithms
# =================================


class _NodeSelection:
    def select(self, nodes: list, req: Request, strategy: str = ''):
        return []


class _SimpleNodeSelection(_NodeSelection):
    def select(self, nodes: list, req: Request, strategy: str = ''):
        def _check_resources(node: Node, req: Request):
            return (node != req.src  # exclude source node
                    and node.state == True
                    and (node.get_cpu_free() - req.get_min_cpu()
                         >= node.get_cpu_count() * node.threshold)
                    and (node.get_memory_free() - req.get_min_ram()
                         >= node.get_memory_total() * node.threshold)
                    and (node.get_disk_free() - req.get_min_disk()
                         >= node.get_disk_total() * node.threshold))

        if not strategy or strategy == ALL:
            return [node for node in nodes if _check_resources(node, req)]
        elif strategy == FIRST:
            for node in nodes:
                if _check_resources(node, req):
                    return [node]
        else:
            console.error('%s strategy not applicable in %s algorithm',
                          strategy, SIMPLE_NODE)
            file.error('%s strategy not applicable in %s algorithm',
                       strategy, SIMPLE_NODE)
            return []


# =================================
#     Path Selection Algorithms
# =================================


class _PathSelection:
    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        return {}, {}


class _DijkstraPathSelection(_PathSelection):
    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        if weight == DELAY_WEIGHT:
            def weight_func(u, v, d):
                return d['link'].get_delay()
        else:
            weight_func = 1

        # TODO calculate cutoff from requirements

        lengths, paths = single_source_dijkstra(graph, req.src.id,
                                                cutoff=None,
                                                weight=weight_func)

        targs = targets
        if targs and isinstance(targs[0], Node):
            targs = [target.id for target in targets]

        if not strategy or strategy == ALL:
            return ({target: [paths[target]]
                     for target in paths if target in targs},
                    {target: [lengths[target]]
                     for target in lengths if target in targs})

        elif strategy == BEST:
            best_length = float('inf')
            best_path = None
            best_target = None
            for target in lengths:
                if target in targs and lengths[target] < best_length:
                    best_length = lengths[target]
                    best_path = paths[target]
                    best_target = target
            return {best_target: [best_path]}, {best_target: [best_length]}

        else:
            console.error('%s strategy not applicable in %s algorithm',
                          strategy, DIJKSTRA_PATH)
            file.error('%s strategy not applicable in %s algorithm',
                       strategy, DIJKSTRA_PATH)
            return {}, {}


class _LeastCostPathSelection(_PathSelection):
    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        def calc_cost(path: list):
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

        targs = targets
        if targs and isinstance(targs[0], Node):
            targs = [target.id for target in targets]

        paths = all_simple_paths(graph, req.src.id, targs)

        if not strategy or strategy == ALL:
            weights = {}
            paths_dict = {}
        elif strategy == BEST:
            best_Cpath = float('inf')
            best_path = None
            best_target = None

        for path in paths:
            try:
                Cpath = calc_cost(path)
            except:
                Cpath = float('inf')

            dst = path[-1]
            if not strategy or strategy == ALL:
                weights.setdefault(dst, [])
                weights[dst].append(Cpath)
                paths_dict.setdefault(dst, [])
                paths_dict[dst].append(path)
            elif strategy == BEST:
                if Cpath < best_Cpath:
                    best_Cpath = Cpath
                    best_path = path
                    best_target = dst

        if not strategy or strategy == ALL:
            return paths_dict, weights
        elif strategy == BEST:
            return {best_target: [best_path], best_target: [best_Cpath]}
        else:
            console.error('%s strategy not applicable in %s algorithm',
                          strategy, LEASTCOST_PATH)
            file.error('%s strategy not applicable in %s algorithm',
                       strategy, LEASTCOST_PATH)
            return {}, {}


# ================================
#     Algorithms Access Points
# ================================


# host selection algorithms
SIMPLE_NODE = 'SIMPLE'
NODE_ALGORITHMS = {
    SIMPLE_NODE: _SimpleNodeSelection
}

# path selection algorithms
DIJKSTRA_PATH = 'DIJKSTRA'
LEASTCOST_PATH = 'LEASTCOST'
PATH_ALGORITHMS = {
    DIJKSTRA_PATH: _DijkstraPathSelection,
    LEASTCOST_PATH: _LeastCostPathSelection
}

# path weights
HOP_WEIGHT = 'HOP'
DELAY_WEIGHT = 'DELAY'
COST_WEIGHT = 'COST'
PATH_WEIGHTS = {
    DIJKSTRA_PATH: [HOP_WEIGHT, DELAY_WEIGHT],
    LEASTCOST_PATH: [COST_WEIGHT]
}

# selection strategies
ALL = 'ALL'
FIRST = 'FIRST'
BEST = 'BEST'


class NodeSelector:
    '''
        Node selector through given algorithm.

        Algorithms:
        -----------
        SIMPLE: Simple selection of nodes that satisfy required CPU, RAM, 
        and disk.

        Methods:
        --------
        select(nodes, req, strategy): Select node(s) that satisfy req through
        given algorithm and based on given strategy (ALL or FIRST). Default
        strategy is ALL.
    '''

    def __init__(self, algorithm: str = ''):
        try:
            self._algorithm = NODE_ALGORITHMS[algorithm.upper()]()
        except:
            console.error('Requested node algorithm not found. '
                          'Defaulting to %s', SIMPLE_NODE)
            file.exception('Requested node algorithm not found')
            self._algorithm = _SimpleNodeSelection()

    def select(self, nodes: list, req: Request, strategy: str = ''):
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
        and based on given weight (HOP, DELAY, or COST) and given strategy
        (ALL or BEST). Default weight is HOP (all edges are equal). Default 
        strategy is ALL.
    '''

    def __init__(self, algorithm: str = ''):
        try:
            self._algorithm = PATH_ALGORITHMS[algorithm.upper()]()
        except:
            console.error('Requested path algorithm not found. '
                          'Defaulting to %s', DIJKSTRA_PATH)
            file.exception('Requested path algorithm not found')
            self._algorithm = _DijkstraPathSelection()

    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        '''
            Select path(s) in graph from req.src to target Nodes, that satisfy
            req through given algorithm and based on given weight (HOP, DELAY,
            or COST) and given strategy (ALL or BEST). Default weight is HOP 
            (all edges are equal). Default strategy is ALL.

            Returns selected path(s) and weight(s).
        '''

        return self._algorithm.select(graph, targets, req, weight, strategy)
