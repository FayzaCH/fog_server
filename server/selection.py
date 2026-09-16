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

    LEASTCOST (CBP): Best path selection based on path cost that is calculated with
    an equation that includes bandwidth cost, delay cost, jitter cost, and
    loss rate cost.

    AHP : Best path selection based on path score that is calculated with an 
    equation that includes coefficients for bandwidth, delay, jitter, and loss
    rate evaluated for each CoS using the Analytic Hierarchy Process (AHP) Method. 
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
               weight: str = '', strategy: str = '', relax: bool = False):
        return []


class _DijkstraPathSelection(_PathSelection):
    def select(self, topo: Topology, targets: list, req: Request,
               weight: str = '', strategy: str = '', relax: bool = False):
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
               weight: str = '', strategy: str = '', relax: bool = False):
        def calc_cost(path: list) -> float:
            len_path = len(path)
            if len_path < 2:
                return float('inf')
            
            BWp = float('inf')      # Path free bandwidth min 
            Dp = 0.0                # Path total delay
            Jp = 0.0                # Path total jitter
            success_rate = 1.0      # Path transmission success rate product
            
            for i in range(1, len_path):
                Pi = topo.get_link(path[i-1], path[i])
                if Pi is None:
                    return float('inf')

                free_bw = Pi.get_bandwidth()

                BWp = min(BWp, free_bw)
                Dp += Pi.get_delay()
                Jp += Pi.get_jitter()
                success_rate *= (1.0 - Pi.get_loss_rate())
            # Path loss rate : 1 - \prod (1 - lr_l)

            LRp = 1.0 - success_rate

            EPSILON = 1e-9

            #1. Bandwidth cost
            BWc = req.get_min_bandwidth()
            remaining_bw = BWp - BWc
            if remaining_bw <= 0:
                return float('inf')
            
            CBWp = BWc / remaining_bw

            #2. Delay, Jitter, and Loss rate costs
            CDp = req.get_max_delay() / Dp if Dp > 0 else float('inf')
            CJp = req.get_max_jitter() / Jp if Jp > 0 else float('inf')
            CLRp = req.get_max_loss_rate() / (LRp + EPSILON)

            # 3. Final constraint-based metric : phi_p
            denom_phi = CDp * CJp * CLRp
            if denom_phi <= 0:
                return float('inf')
            
            return CBWp / denom_phi

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
               weight: str = '', strategy: str = '', relax: bool = False):
        '''
            relax : decides up front whether to relax the constraints on path selection or not.
            If True, the algorithm will return the ordered best paths based on AHP score, even
            if they don't meet the hard requirements of min bandwidth, max delay, max jitter, and max loss rate.  
        '''
        def calc_metrics(path: list):
            '''
                Compute the raw (non-normalised) per-path metrics: minimum
                free bandwidth, total delay, total jotter, and total ross 
                rate. Returns None if the path is structurally invalid or
                violates  hard requirement (min bandwidth, max delay, max
                jitter, max loss rate) of req.
            '''
            len_path = len(path)
            if len_path < 2:
                return None
            
            BWp = float('inf')
            Dp = 0.0
            Jp = 0.0
            success_rate = 1.0

            for i in range(1, len_path):
                Pi = topo.get_link(path[i-1], path[i])
                if Pi is None:
                    return None
                
                free_bw = Pi.get_bandwidth()

                BWp = min(BWp, free_bw)
                Dp += Pi.get_delay()
                Jp += Pi.get_jitter()
                success_rate *= (1.0 - Pi.get_loss_rate())

            LRp = 1.0 - success_rate



            #exclude paths that don't match required values of bw, delay, jitter and LR
            #if (Dp > req.get_max_delay() or Jp > req.get_max_jitter() or 
            #    LRp > req.get_max_loss_rate() or BWp < req.get_min_bandwidth()):
            #    return None
            #flag paths that don't match required values of bw, delay, jitter and Loss Rate

            feasible = not( Dp > req.get_max_delay() or Jp > req.get_max_jitter() or LRp > req.get_max_loss_rate() or BWp < req.get_min_bandwidth())

            return{'path': path, 'BW': BWp, 'D': Dp, 'J': Jp, 'LR': LRp, 'feasible': feasible}
        
        def get_coefs():
            '''
                Return the (coef_bw, coef_Delay, coef_Jitter, coef_LossRate)
                AHP weights tuple for req's class of service, or None if the 
                class of service is unknown.
            '''        
            if req.cos.id == 1:
                return 0.120, 0.134, 0, 0.746

            elif req.cos.id == 2:
                return 0.528, 0.116, 0.047, 0.309

            elif req.cos.id == 3:
                return 0.545, 0.117, 0.063, 0.275

            elif req.cos.id == 4:
                return 0.154, 0.406, 0.124, 0.316

            elif req.cos.id == 5:
                return 0.165, 0.496, 0.048, 0.292

            elif req.cos.id == 6:
                return 0.088, 0.482, 0.158, 0.272

            elif req.cos.id == 7:
                return 0.090, 0.406, 0.143, 0.361

            else :
                console.error('%s does not exist ', req.cos.id)
                file.error('%s does not exist', req.cos.id)
                return None
            
        def normalize(value, vmin, vmax, higher_is_better):
            '''
            Min-Max Normalisation of a metric against observed
             [vmin, vmax] range across all candidate paths. For
             lower-is-better metrics (Delay, Jitter, Loss Rate) the
             formula is inverted: mu = (kmax - kp) / (kmax - kmin).
             When every candidate path has the same value of this
             metric (vmax == vmin), it carries no discriminative power, 
             so it's normalised to 1.0. 
            '''
            if vmax == vmin:
                return 1.0
            if higher_is_better:
                return (value- vmin) / (vmax - vmin)
            return (vmax - value) / (vmax - vmin)

        coefs = get_coefs()
        if coefs is None:
            return[]
        coef_bw, coef_Delay, coef_Jitter, coef_LossRate = coefs
        graph = topo.get_graph()
        raw_paths = all_simple_paths(graph, req.src.id,
                                     [target.id for target in targets])
        # --- Pass 1: gather raw metrics for every feasible path ---
        candidates = []
        for path in raw_paths:
            try:
                metrics = calc_metrics(path)     
            except:
                metrics = None
            if metrics is not None and (relax or metrics['feasible']):
                candidates.append(metrics)

        if not strategy or strategy == ALL:
            ret = []
        elif strategy == BEST:
            best_Upath = float('-inf')
            best_path = None
        else:
            console.error('%s strategy not applicable in %s algorithm',
                          strategy, AHP_PATH)
            file.error('%s strategy not applicable in %s algorithm',
                       strategy, AHP_PATH)
            return[]

        # --- Pass 2: Min-Max normalise each metric across candidates,
        # then compute the AHP utility score U_p for each path ---

        if candidates:
            bw_min = min(c['BW'] for c in candidates)
            bw_max = max(c['BW'] for c in candidates)
            d_min = min(c['D'] for c in candidates)
            d_max = max(c['D'] for c in candidates)
            j_min = min(c['J'] for c in candidates)
            j_max = max(c['J'] for c in candidates)
            lr_min = min(c['LR'] for c in candidates)
            lr_max = max(c['LR'] for c in candidates)

            for c in candidates:
                        mu_bw = normalize(c['BW'], bw_min, bw_max,
                                            higher_is_better=True)
                        mu_D = normalize(c['D'], d_min, d_max, higher_is_better = False)
                        mu_J = normalize(c['J'], j_min, j_max, higher_is_better=False)
                        mu_LR = normalize(c['LR'], lr_min, lr_max, higher_is_better=False)

                        Upath = (coef_bw * mu_bw) + (coef_Delay * mu_D) + (coef_Jitter * mu_J) + (coef_LossRate * mu_LR)

                        if not strategy or strategy == ALL:
                            insort(ret, {'path': c['path'], 'length': Upath}, key=lambda x: x['length'], reverse=True)
                        elif strategy == BEST:
                          if Upath > best_Upath:
                              best_Upath = Upath
                              best_path = c['path']


        if not strategy or strategy == ALL:
            return ret

        else: # strategy == BEST
            return [{'path': best_path, 'length': best_Upath}]

        
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

        LEASTCOST (CBP): Best path selection based on path cost that is calculated
        with an equation that includes bandwidth cost, delay cost, jitter cost,
        and loss rate cost.

        AHP : Best path selection based on path score that is calculated with an 
        equation that includes coefficients for bandwidth, delay, jitter, and loss
        rate evaluated for each CoS using the Analytic Hierarchy Process (AHP) Method.

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
               weight: str = '', strategy: str = '', relax: bool = False):
        '''
            Select path(s) in graph from req.src to target Nodes, that satisfy
            req through given algorithm and based on given weight (HOP, DELAY,
            or COST) and given strategy (ALL or BEST). Default weight is HOP 
            (all edges are equal). Default strategy is ALL.

            relax (only for AHP algorithm; ignored for other algorithms) : if True, every
            structurally valid path is considered, even if it doesn't meet the hard reqirements
            of bw, delay, jitter, and loss rate. Default is False. 

            Returns list of dicts of selected path(s) and length(s).
        '''

        return self._algorithm.select(topo, targets, req, weight, strategy, relax)


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
