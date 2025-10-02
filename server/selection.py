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


from platform import python_version
from bisect import insort_left, bisect_left

from networkx import single_source_dijkstra, all_simple_paths

from model import Topology, Node, Request
from logger import console, file


# =================================
#     Node Selection Algorithms
# =================================


class _NodeSelection:
    def select(self, topo: Topology, req: Request, strategy: str = ''):
        return []


class _SimpleNodeSelection(_NodeSelection):
    def select(self, topo: Topology, req: Request, strategy: str = ''):
        def _check_resources(node: Node, req: Request):
            return (node != req.src  # exclude source node
                    and node.state == True
                    and (node.get_cpu_free() - req.get_min_cpu()
                         >= node.get_cpu_count() * node.threshold)
                    and (node.get_memory_free() - req.get_min_ram()
                         >= node.get_memory_total() * node.threshold)
                    and (node.get_disk_free() - req.get_min_disk()
                         >= node.get_disk_total() * node.threshold))

        nodes = topo.get_nodes().values()

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
    def select(self, topo: Topology, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        return []


class _DijkstraPathSelection(_PathSelection):
    def select(self, topo: Topology, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        cutoff = None
        weight_func = 1
        if weight == DELAY_WEIGHT:
            def weight_func(_, __, d):
                return d['link'].get_delay()
            cutoff = req.get_max_delay()

        # even if we call networkx.dijkstra_path(...) with specific targets
        # networkx will always call single_source_dijkstra(...) and calculate
        # all paths between source and all targets (check networkx code)
        # so might as well get all paths and reformat them as we want
        graph = topo.get_graph()
        lengths, paths = single_source_dijkstra(graph, req.src.id,
                                                cutoff=cutoff,
                                                weight=weight_func)

        if not strategy or strategy == ALL:
            ret = []
            for target in targets:
                targ_id = target.id
                if targ_id in lengths:
                    insort(
                        ret,
                        {'path': paths[targ_id], 'length': lengths[targ_id]},
                        key=lambda x: x['length'], reverse=False)
            return ret

        elif strategy == BEST:
            best_length = float('inf')
            best_path = None
            for target in targets:
                targ_id = target.id
                if targ_id in lengths and lengths[targ_id] < best_length:
                    best_length = lengths[targ_id]
                    best_path = paths[targ_id]
            return [{'path': best_path, 'length': best_length}]

        else:
            console.error('%s strategy not applicable in %s algorithm',
                          strategy, DIJKSTRA_PATH)
            file.error('%s strategy not applicable in %s algorithm',
                       strategy, DIJKSTRA_PATH)
            return []


class _LeastCostPathSelection(_PathSelection):
    def select(self, topo: Topology, targets: list, req: Request,
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
                Pi = topo.get_link(path[i-1], path[i])
                ## TODO : check this part
                cap = Pi.get_capacity()                
                Ct = min(Ct, cap)
                free_bw = Pi.get_bandwidth()
                BWp = min(BWp, free_bw)
                Bw += (cap - free_bw)
                ###
                Dp += Pi.get_delay()
                Jp += Pi.get_jitter()
                LRp *= (1 - Pi.get_loss_rate())
            LRp = 1 - LRp
            ## exception : all links' loss_rate values are zero, cost of the path loss rate is set to request's max_loss_rate 
            if LRp == 0 :
                LRp = req.get_max_loss_rate()

            CDp = req.get_max_delay() / Dp
            CJp = req.get_max_jitter() / Jp
            CLRp = req.get_max_loss_rate() / LRp
            BWc = req.get_min_bandwidth()
            ## TODO:  and check this part
            CBWp = BWc / (Ct - (Bw + BWc))
            ##
            return CBWp / (CDp * CJp * CLRp)

        graph = topo.get_graph()
        paths = all_simple_paths(graph, req.src.id,
                                 [target.id for target in targets])

        if not strategy or strategy == ALL:
            ret = []

        if strategy == BEST:
            best_Cpath = float('inf')
            best_path = None

        for path in paths:
            try:
                Cpath = calc_cost(path)
            except:
                Cpath = float('inf')

            if not strategy or strategy == ALL:
                insort(ret, {'path': path, 'length': Cpath},
                       key=lambda x: x['length'], reverse=False)

            elif strategy == BEST:
                if Cpath < best_Cpath:
                    best_Cpath = Cpath
                    best_path = path

        if not strategy or strategy == ALL:
            return ret

        elif strategy == BEST:
            return [{'path': best_path, 'length': best_Cpath}]

        else:
            console.error('%s strategy not applicable in %s algorithm',
                          strategy, LEASTCOST_PATH)
            file.error('%s strategy not applicable in %s algorithm',
                       strategy, LEASTCOST_PATH)
            return []

class _AHPCostPathSelection(_PathSelection):
    def select(self, topo: Topology, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        def calc_cost(path: list):
            len_path = len(path)
            BWp = float('inf')
            Dp = 0
            Jp = 0
            LRp = 1
            for i in range(1, len_path):
                Pi = topo.get_link(path[i-1], path[i])
                BWp = min(BWp, Pi.get_bandwidth())
                Dp += Pi.get_delay()
                Jp += Pi.get_jitter()
                LRp *= (1 - Pi.get_loss_rate())
            LRp = 1 - LRp
            #exclude paths that don't match required values of bw, delay, jitter and LR
            if (Dp > req.get_max_delay() or Jp > req.get_max_jitter() or 
                LRp > req.get_max_loss_rate() or BWp < req.get_min_bandwidth()):
                return 0
            if req.cos.id == 1:
                coef_bw = 0.120
                coef_Delay = 0.134
                coef_Jitter = 0
                coef_LossRate =0.746
            elif req.cos.id == 2:
                #console.info('in 2 CoS')
                coef_bw = 0.528
                coef_Delay = 0.116
                coef_Jitter = 0.047
                coef_LossRate =0.309
            elif req.cos.id == 3:
                coef_bw = 0.545
                coef_Delay = 0.117
                coef_Jitter = 0.063
                coef_LossRate =0.275
            elif req.cos.id == 4:
                coef_bw = 0.154
                coef_Delay = 0.406
                coef_Jitter = 0.124
                coef_LossRate =0.316
            elif req.cos.id == 5:
                coef_bw = 0.165
                coef_Delay = 0.496
                coef_Jitter = 0.048
                coef_LossRate =0.292
            elif req.cos.id == 6:
                coef_bw == 0.088
                coef_Delay = 0.482
                coef_Jitter = 0.158
                coef_LossRate =0.272
            elif req.cos.id == 7:
                coef_bw = 0.090
                coef_Delay = 0.406
                coef_Jitter = 0.143
                coef_LossRate =0.361
            else :
                console.error('%s does not exist ', req.cos.id)
                file.error('%s does not exist', req.cos.id)
                return []
            
            return ((coef_Delay * Dp) + (coef_Jitter * Jp) + (coef_LossRate * LRp ) + (coef_bw * BWp))

        graph = topo.get_graph()
        paths = all_simple_paths(graph, req.src.id,
                                 [target.id for target in targets])

        if not strategy or strategy == ALL:
            ret = []

        if strategy == BEST:
            best_Cpath = float('inf')
            best_path = None

        for path in paths:
            try:
                Cpath = calc_cost(path)
            except:
                Cpath = float('inf')

            if not strategy or strategy == ALL:
                insort(ret, {'path': path, 'length': Cpath},
                       key=lambda x: x['length'], reverse = True)

            elif strategy == BEST:
                if Cpath < best_Cpath:
                    best_Cpath = Cpath
                    best_path = path

        if not strategy or strategy == ALL:
            return ret

        elif strategy == BEST:
            return [{'path': best_path, 'length': best_Cpath}]

        else:
            console.error('%s strategy not applicable in %s algorithm',
                          strategy, LEASTCOST_PATH)
            file.error('%s strategy not applicable in %s algorithm',
                       strategy, LEASTCOST_PATH)
            return []
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
AHP_PATH = 'AHP'
PATH_ALGORITHMS = {
    DIJKSTRA_PATH: _DijkstraPathSelection,
    LEASTCOST_PATH: _LeastCostPathSelection,
    AHP_PATH: _AHPCostPathSelection
}

# path weights
HOP_WEIGHT = 'HOP'
DELAY_WEIGHT = 'DELAY'
COST_WEIGHT = 'COST'
AHP_WEIGHT= 'AHP'
PATH_WEIGHTS = {
    DIJKSTRA_PATH: [HOP_WEIGHT, DELAY_WEIGHT],
    LEASTCOST_PATH: [COST_WEIGHT],
    AHP_PATH: [AHP_WEIGHT]
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

    def select(self, topo: Topology, req: Request, strategy: str = ''):
        '''
            Select node(s) that satisfy req through given algorithm and based
            on given strategy (ALL or FIRST). Default strategy is ALL.

            Returns list of selected Node(s).
        '''

        return self._algorithm.select(topo, req, strategy)


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

    def select(self, topo: Topology, targets: list, req: Request,
               weight: str = '', strategy: str = ''):
        '''
            Select path(s) in graph from req.src to target Nodes, that satisfy
            req through given algorithm and based on given weight (HOP, DELAY,
            or COST) and given strategy (ALL or BEST). Default weight is HOP 
            (all edges are equal). Default strategy is ALL.

            Returns list of dicts of selected path(s) and length(s).
        '''

        return self._algorithm.select(topo, targets, req, weight, strategy)


# =============
#     UTILS
# =============


class _KeyWrapper:
    def __init__(self, iterable, key, reverse):
        self.it = iterable
        self.key = key
        self.reverse = reverse

    def __getitem__(self, i):
        val=self.key(self.it[i])
        if self.reverse:
            return -val
        return val

    def __len__(self):
        return len(self.it)


def insort(a, x, key=None, reverse=False):
    _key_func = key if key is not None else lambda val:val

    pyv_maj, pyv_min, _ = python_version().split('.')
    pyv = int(pyv_maj) * 100 + int(pyv_min)
    search_value = _key_func(x)
    if reverse:
        search_value = -search_value

    if pyv < 310:
        bslindex = bisect_left(_KeyWrapper(a, key=_key_func, reverse=reverse), search_value)
        a.insert(bslindex, x)
    else:
        def get_bisect_key(val):
            val=_key_func(val)
            return -val if reverse else val
        
        insort_left(a, x, key=key)
