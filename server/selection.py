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
'''


from networkx import DiGraph, single_source_dijkstra

from model import Node, Request


# host selection algorithms
SIMPLE_NODE = 'SIMPLE'

# path selection algorithms
DIJKSTRA_PATH = 'DIJKSTRA'

# path weights
HOP_WEIGHT = 'HOP'
DELAY_WEIGHT = 'DELAY'
BANDWIDTH_WEIGHT = 'BANDWIDTH'

# selection strategies
ALL = 'ALL'
FIRST = 'FIRST'
BEST = 'BEST'

NODE_ALGORITHMS = [None, '', SIMPLE_NODE]
PATH_ALGORITHMS = [None, '', DIJKSTRA_PATH]
WEIGHTS = [None, '', HOP_WEIGHT, DELAY_WEIGHT, BANDWIDTH_WEIGHT]
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
        return self._algorithm.select(nodes, req, strategy)


class PathSelector:
    '''
        Path selector through given algorithm. 

        Algorithms:
        -----------
        DIJKSTRA: Best path selection based on Dijkstra's shortest path 
        algorithm. Calculates link weights and gets the shortest path from the 
        source node to each potential destination node.

        Methods:
        --------
        select(graph, dst, req, weight, strategy): Select path(s) in graph 
        from req.src to target Nodes, that satisfy req through given algorithm 
        and based on given weight (HOP, DELAY, BANDWIDTH) and given strategy 
        (ALL or BEST). Default weight is nothing (all edges are equal). 
        Default strategy is ALL.
    '''

    def __init__(self, algorithm: str = ''):
        if not algorithm or algorithm.upper() == DIJKSTRA_PATH:
            self._algorithm = _DijkstraPathSelection()
        else:
            raise Exception('Requested algorithm does not exist')

    def select(self, graph: DiGraph, targets: list, req: Request,
               weight: str = '', strategy: str = ALL):
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
        # TODO calculate cutoff from requirements
        if weight == DELAY_WEIGHT:
            def weight_func(u, v, d): return d['link'].get_delay()
        elif weight == BANDWIDTH_WEIGHT:
            def weight_func(u, v, d): return d['link'].get_bandwidth()
        else:
            weight_func = 1
        lengths, paths = single_source_dijkstra(graph, req.src.id, cutoff=None,
                                                weight=weight_func)
        targets = [target.id for target in targets]
        if strategy == ALL:
            return ({target: lengths[target]
                     for target in lengths if target in targets},
                    {target: paths[target]
                     for target in paths if target in targets})
        if strategy == BEST:
            best_length = float('inf')
            best_path = None
            for target in lengths:
                if target in targets and lengths[target] < best_length:
                    best_length = lengths[target]
                    best_path = paths[target]
            return best_length, best_path


'''
        def _calc_weight(graph: DiGraph, weight: str = ''):
            if weight == BANDWIDTH_WEIGHT or weight == DELAY_WEIGHT:
                for _, _, data in graph.edges(data=True):
                    link = data['link']
                    if not link.state:
                        data['weight'] = float('inf')
                    else:
                        if weight == BANDWIDTH_WEIGHT:
                            data['weight'] = data['link'].get_bandwidth()
                        elif weight == DELAY_WEIGHT:
                            data['weight'] = data['link'].get_delay()
'''
